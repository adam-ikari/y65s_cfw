//! Tauri command surface of the YD-Y65S tool.

use std::time::Duration;

use serde::Serialize;
use time::OffsetDateTime;
use y65s_core::error::Y65sError;
use y65s_core::isp;
use y65s_core::keys;
use y65s_core::protocol::{self, Profile};
use y65s_core::Keyboard;

/// Everything the UI needs to know about the keyboard.
#[derive(Debug, Clone, Serialize)]
pub struct Status {
    /// The keyboard is reachable.
    pub connected: bool,
    /// Which HID backend we used.
    pub backend: String,
    /// The HID collections we can see.
    pub collections: Vec<y65s_core::DeviceInfo>,
    /// A free form note (e.g. "设备被占用").
    pub note: String,
}

/// One profile field with its value.
#[derive(Debug, Clone, Serialize)]
pub struct FieldView {
    /// Byte offset in the profile.
    pub offset: u8,
    /// Field name.
    pub name: String,
    /// Current value.
    pub value: u8,
    /// Factory value.
    pub factory: u8,
}

/// The profile as the UI sees it.
#[derive(Debug, Clone, Serialize)]
pub struct ProfileView {
    /// The raw bytes.
    pub bytes: Vec<u8>,
    /// The known fields.
    pub fields: Vec<FieldView>,
}

/// The result of a clock delivery.
#[derive(Debug, Clone, Serialize)]
pub struct ClockReport {
    /// What we sent, per route.
    pub attempts: Vec<ClockAttemptView>,
}

/// One clock attempt.
#[derive(Debug, Clone, Serialize)]
pub struct ClockAttemptView {
    /// The route that was used.
    pub record: u8,
    /// Offset inside the record.
    pub at: usize,
    /// Sub-dispatch value.
    pub sub: Option<u8>,
    /// The time we sent.
    pub time: String,
    /// The answer frame, hex.
    pub answer: String,
}

fn map_err(e: Y65sError) -> String {
    e.full()
}

/// Is the keyboard reachable?
#[tauri::command]
pub fn status() -> Result<Status, String> {
    let collections = y65s_core::hid::list_collections().map_err(map_err)?;
    match Keyboard::open() {
        Ok(kb) => Ok(Status {
            connected: true,
            backend: kb.backend().to_string(),
            collections,
            note: String::new(),
        }),
        Err(e) => Ok(Status {
            connected: false,
            backend: "unknown".into(),
            collections,
            note: map_err(e),
        }),
    }
}

/// The HID collections of the keyboard.
#[tauri::command]
pub fn list_collections() -> Result<Vec<y65s_core::DeviceInfo>, String> {
    y65s_core::hid::list_collections().map_err(map_err)
}

/// Read the live profile out of a flash dump.
#[tauri::command]
pub fn read_profile(dump: String) -> Result<ProfileView, String> {
    let data = std::fs::read(&dump).map_err(|e| format!("{dump}: {e}"))?;
    let profile = Profile::from_dump(&data, true).map_err(map_err)?;
    Ok(view(&profile))
}

/// Change the lighting and/or the volume and push the profile to the module.
#[tauri::command]
pub fn write_profile(
    dump: String,
    effect: Option<u8>,
    mode: Option<u8>,
    volume: Option<u8>,
) -> Result<ProfileView, String> {
    let data = std::fs::read(&dump).map_err(|e| format!("{dump}: {e}"))?;
    let mut profile = Profile::from_dump(&data, true).map_err(map_err)?;
    profile.set_lighting(effect, mode);
    if let Some(v) = volume {
        profile.set_volume(v);
    }
    profile.stamp_marker();
    let kb = Keyboard::open().map_err(map_err)?;
    kb.write_profile(&profile).map_err(map_err)?;
    Ok(view(&profile))
}

/// Write the factory profile back to the module.
#[tauri::command]
pub fn factory_restore(dump: String) -> Result<ProfileView, String> {
    let data = std::fs::read(&dump).map_err(|e| format!("{dump}: {e}"))?;
    let profile = Profile::from_dump(&data, false).map_err(map_err)?;
    let kb = Keyboard::open().map_err(map_err)?;
    kb.write_profile(&profile).map_err(map_err)?;
    Ok(view(&profile))
}

/// Push the PC clock into the module.
///
/// With `sweep` every known route is tried, each with a different minute, so
/// the screen shows which one was accepted.
#[tauri::command]
pub fn set_clock(sweep: bool) -> Result<ClockReport, String> {
    let kb = Keyboard::open().map_err(map_err)?;
    let now = OffsetDateTime::now_local().unwrap_or_else(|_| OffsetDateTime::now_utc());
    if !sweep {
        let payload = y65s_core::clock_payload_for(now);
        let route = protocol::CLOCK_ROUTES[0];
        kb.send_record(&protocol::record_with_sub(
            route.record,
            &payload,
            route.at,
            route.sub,
        ))
        .map_err(map_err)?;
        return Ok(ClockReport {
            attempts: vec![ClockAttemptView {
                record: route.record,
                at: route.at,
                sub: route.sub,
                time: format!("{:02}:{:02}", now.hour(), now.minute()),
                answer: String::new(),
            }],
        });
    }
    let attempts = kb.set_clock_sweep(now).map_err(map_err)?;
    Ok(ClockReport {
        attempts: attempts
            .into_iter()
            .map(|a| ClockAttemptView {
                record: a.route.record,
                at: a.route.at,
                sub: a.route.sub,
                time: a.time,
                answer: a
                    .answer
                    .iter()
                    .map(|b| format!("{b:02x}"))
                    .collect::<Vec<_>>()
                    .join(" "),
            })
            .collect(),
    })
}



/// Read the whole flash of the keyboard (ISP).
#[tauri::command]
pub fn flash_read(path: String) -> Result<String, String> {
    let _ = isp::enter_isp().map_err(map_err)?;
    isp::wait_for_isp(Duration::from_secs(20)).map_err(map_err)?;
    let session = isp::Isp::open().map_err(map_err)?;
    let data = session.read(0, isp::FLASH_SIZE).map_err(map_err)?;
    std::fs::write(&path, &data).map_err(|e| format!("{path}: {e}"))?;
    session.reboot().map_err(map_err)?;
    Ok(format!("已备份 {} 字节到 {path}", data.len()))
}

/// Write a flash image back to the keyboard (ISP).
#[tauri::command]
pub fn flash_write(path: String) -> Result<String, String> {
    let data = std::fs::read(&path).map_err(|e| format!("{path}: {e}"))?;
    if data.len() < isp::FIRMWARE_SIZE {
        return Err(format!(
            "镜像太小：{} 字节，至少需要 {} 字节",
            data.len(),
            isp::FIRMWARE_SIZE
        ));
    }
    let _ = isp::enter_isp().map_err(map_err)?;
    isp::wait_for_isp(Duration::from_secs(20)).map_err(map_err)?;
    let session = isp::Isp::open().map_err(map_err)?;
    session.erase().map_err(map_err)?;
    session.write(0, &data[..isp::FIRMWARE_SIZE]).map_err(map_err)?;
    session.reboot().map_err(map_err)?;
    Ok(format!("已写入 {} 字节", isp::FIRMWARE_SIZE))
}

/// The key combinations the keyboard understands.
#[tauri::command]
pub fn key_combos() -> Vec<keys::Combo> {
    keys::COMBOS.to_vec()
}

/// The wireless link modes.
#[tauri::command]
pub fn link_modes() -> Vec<keys::LinkMode> {
    keys::LINK_MODES.to_vec()
}

/// The patches our custom firmware is made of.
#[tauri::command]
pub fn list_patches() -> Vec<y65s_core::patch::Patch> {
    y65s_core::patch::PATCHES.to_vec()
}

/// Check the patch set against a flash dump.
#[tauri::command]
pub fn check_patches(dump: String) -> Result<Vec<y65s_core::patch::PatchReport>, String> {
    let data = std::fs::read(&dump).map_err(|e| format!("{dump}: {e}"))?;
    Ok(y65s_core::patch::check(&data, y65s_core::patch::PATCHES))
}

/// Build a patched firmware image from a dump.
#[tauri::command]
pub fn build_patched(dump: String, out: String, ids: Vec<String>) -> Result<String, String> {
    let data = std::fs::read(&dump).map_err(|e| format!("{dump}: {e}"))?;
    let patches = y65s_core::patch::select(&ids).map_err(map_err)?;
    let patched = y65s_core::patch::apply_all(&data, &patches).map_err(map_err)?;
    std::fs::write(&out, &patched).map_err(|e| format!("{out}: {e}"))?;
    Ok(format!(
        "已按 {} 条补丁生成 {out}（{} 字节）",
        patches.len(),
        patched.len()
    ))
}

fn view(profile: &Profile) -> ProfileView {
    ProfileView {
        bytes: profile.bytes().to_vec(),
        fields: profile
            .fields()
            .into_iter()
            .map(|(f, v)| FieldView {
                offset: f.offset,
                name: f.name.to_string(),
                value: v,
                factory: f.factory,
            })
            .collect(),
    }
}
