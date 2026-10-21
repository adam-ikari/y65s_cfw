//! One click operations on the keyboard's flash.
//!
//! The operation the tool exists for: *make the screen stop drawing a
//! volume bar that does not match the system*.
//!
//! It works on the user's own firmware, not on a prebuilt image:
//!
//! 1. read the whole flash (nothing is written yet),
//! 2. write that read back to disk -- the backup is the way out,
//! 3. apply the reviewed byte level patches, each of which refuses to apply
//!    when the bytes it expects are not the ones it was written against,
//! 4. erase, write, enable, reboot,
//! 5. read the flash back and compare it byte for byte.
//!
//! The user's profile (lighting, key map, clock) survives, because only the
//! patched bytes are rewritten.

use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::error::{Result, Y65sError};
use crate::isp::{self, Isp};
use crate::patch;

/// The patches that together make the screen stop drawing the volume bar.
///
/// * `no-volume-send` -- the 8051 stops copying the profile volume byte into
///   the settings block it sends to the screen SoC.
/// * `no-volume-ods` -- the volume knob stops notifying the screen SoC,
///   while the HID consumer usage that drives the *host* volume stays.
pub const VOLUME_FIX: &[&str] = &["no-volume-send", "no-volume-ods"];

/// What the fix did, step by step.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct FixReport {
    /// Human readable log, one line per step.
    pub steps: Vec<String>,
    /// Where the pre-flash backup was written, if it was.
    pub backup: Option<String>,
    /// md5 of the backup.
    pub backup_md5: String,
    /// md5 of the image that was written.
    pub image_md5: String,
    /// Whether the read-back matched byte for byte.
    pub verified: bool,
    /// The patches that were applied.
    pub applied: Vec<String>,
    /// Whether the keyboard already carried the fix (nothing was written).
    pub already_fixed: bool,
}

/// md5 of a buffer, lower case hex.
pub fn md5_hex(data: &[u8]) -> String {
    use md5::{Digest, Md5};
    let mut hasher = Md5::new();
    hasher.update(data);
    format!("{:x}", hasher.finalize())
}

/// A default name for the backup file.
pub fn default_backup_path() -> PathBuf {
    let now = time::OffsetDateTime::now_utc();
    PathBuf::from(format!(
        "YD-Y65S_backup_{:04}{:02}{:02}-{:02}{:02}{:02}.bin",
        now.year(),
        now.month() as u8,
        now.day(),
        now.hour(),
        now.minute(),
        now.second()
    ))
}

/// Read the whole flash of the keyboard, without writing anything.
pub fn backup_to(path: &Path) -> Result<(Vec<u8>, String)> {
    let _ = isp::enter_isp()?;
    isp::wait_for_isp(Duration::from_secs(20))?;
    let session = Isp::open()?;
    let flash = session.read(0, isp::FLASH_SIZE)?;
    session.reboot()?;
    isp::wait_for_app(Duration::from_secs(20))?;
    std::fs::write(path, &flash)?;
    let digest = md5_hex(&flash);
    Ok((flash, digest))
}

/// Fix the volume bar: read, back up, patch, write, verify.
///
/// `backup_path` is where the pre-flash image is saved; when it is `None`
/// a timestamped file in the current directory is used.
pub fn fix_volume_bar(backup_path: Option<&Path>) -> Result<FixReport> {
    let mut steps: Vec<String> = Vec::new();

    steps.push("进入 ISP 模式…".into());
    let _ = isp::enter_isp()?;
    isp::wait_for_isp(Duration::from_secs(20))?;
    let session = Isp::open()?;

    steps.push("读取整块 flash…".into());
    let flash = session.read(0, isp::FLASH_SIZE)?;
    let backup_md5 = md5_hex(&flash);
    steps.push(format!("读出 {} 字节，md5={}", flash.len(), backup_md5));

    let path = backup_path
        .map(PathBuf::from)
        .unwrap_or_else(default_backup_path);
    std::fs::write(&path, &flash)?;
    let backup = Some(path.to_string_lossy().into_owned());
    steps.push(format!("已备份到 {}", path.display()));

    // Only the patches whose expected bytes are actually there may apply.
    // A keyboard that already carries the fix is left alone.
    let wanted = patch::select(
        &VOLUME_FIX
            .iter()
            .map(|s| s.to_string())
            .collect::<Vec<String>>(),
    )?;
    let applicable: Vec<&patch::Patch> = wanted
        .iter()
        .copied()
        .filter(|p| p.applies_to(&flash))
        .collect();

    if applicable.is_empty() {
        steps.push("这两条补丁都已经在固件里了，无需写入。".into());
        session.reboot()?;
        isp::wait_for_app(Duration::from_secs(20))?;
        let image_md5 = backup_md5.clone();
        return Ok(FixReport {
            steps,
            backup,
            backup_md5,
            image_md5,
            verified: true,
            applied: Vec::new(),
            already_fixed: true,
        });
    }

    let applied: Vec<String> = applicable.iter().map(|p| p.id.to_string()).collect();
    steps.push(format!("应用补丁：{}", applied.join(" + ")));
    let patched = patch::apply_all(&flash, &applicable)?;
    let image_md5 = md5_hex(&patched);
    steps.push(format!("补丁后镜像 md5={image_md5}"));

    steps.push("擦除并写入（这一步不要拔线）…".into());
    session.flash_image(&patched)?;
    session.reboot()?;
    isp::wait_for_app(Duration::from_secs(30))?;
    steps.push("已重启回应用模式。".into());

    steps.push("读回校验…".into());
    let _ = isp::enter_isp()?;
    isp::wait_for_isp(Duration::from_secs(20))?;
    let verify_session = Isp::open()?;
    let readback = verify_session.read(0, isp::FLASH_SIZE)?;
    verify_session.reboot()?;
    isp::wait_for_app(Duration::from_secs(30))?;
    isp::verify_image(&patched, &readback)?;
    steps.push("读回逐字节一致 ✓".into());

    Ok(FixReport {
        steps,
        backup,
        backup_md5,
        image_md5,
        verified: true,
        applied,
        already_fixed: false,
    })
}

/// Build a patched image from a dump on disk, without touching the keyboard.
pub fn build_patched(
    dump: &Path,
    out: &Path,
    ids: &[String],
) -> Result<(Vec<u8>, Vec<String>)> {
    let image = std::fs::read(dump)?;
    let patches = patch::select(ids)?;
    let patched = patch::apply_all(&image, &patches)?;
    std::fs::write(out, &patched)?;
    Ok((patched, patches.iter().map(|p| p.id.to_string()).collect()))
}

/// Flash an image to the keyboard and verify it afterwards.
pub fn flash_image(path: &Path) -> Result<Vec<String>> {
    let mut steps = Vec::new();
    let image = std::fs::read(path)?;
    if image.len() < isp::FIRMWARE_SIZE {
        return Err(Y65sError::BadInput(format!(
            "镜像太小：{} 字节，至少需要 {} 字节",
            image.len(),
            isp::FIRMWARE_SIZE
        )));
    }
    steps.push(format!(
        "镜像 {} 字节，md5={}",
        image.len(),
        md5_hex(&image)
    ));
    steps.push("进入 ISP 模式…".into());
    let _ = isp::enter_isp()?;
    isp::wait_for_isp(Duration::from_secs(20))?;
    let session = Isp::open()?;
    steps.push("擦除并写入（这一步不要拔线）…".into());
    session.flash_image(&image)?;
    session.reboot()?;
    isp::wait_for_app(Duration::from_secs(30))?;
    steps.push("已重启回应用模式。".into());
    steps.push("读回校验…".into());
    let _ = isp::enter_isp()?;
    isp::wait_for_isp(Duration::from_secs(20))?;
    let verify_session = Isp::open()?;
    let readback = verify_session.read(0, isp::FLASH_SIZE)?;
    verify_session.reboot()?;
    isp::wait_for_app(Duration::from_secs(30))?;
    isp::verify_image(&image, &readback)?;
    steps.push("读回逐字节一致 ✓".into());
    Ok(steps)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dump() -> Option<Vec<u8>> {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../firmware/YD-Y65S_full.bin");
        std::fs::read(path).ok()
    }

    #[test]
    fn md5_matches_the_known_digest() {
        assert_eq!(md5_hex(b""), "d41d8cd98f00b204e9800998ecf8427e");
        assert_eq!(md5_hex(b"abc"), "900150983cd24fb0d6963f7d28e17f72");
    }

    /// The two volume patches must fit the factory dump, and applying them
    /// must change bytes only inside their own ranges.
    #[test]
    fn volume_fix_applies_to_the_factory_dump() {
        let Some(image) = dump() else { return };
        let patches = patch::select(
            &VOLUME_FIX
                .iter()
                .map(|s| s.to_string())
                .collect::<Vec<String>>(),
        )
        .unwrap();
        assert_eq!(patches.len(), 2);
        for p in &patches {
            assert!(p.applies_to(&image), "补丁 {} 对不上出厂 dump", p.id);
        }
        let out = patch::apply_all(&image, &patches).unwrap();
        let changed: Vec<usize> = (0..image.len())
            .filter(|i| image[*i] != out[*i])
            .collect();
        assert!(!changed.is_empty());
        for i in changed {
            let inside = patches
                .iter()
                .any(|p| i >= p.address as usize && i < p.address as usize + p.replace.len());
            assert!(inside, "补丁越界改了 0x{i:04X}");
        }
    }

    /// Applying the volume fix twice must fail: the second run no longer
    /// finds the bytes it expects.
    #[test]
    fn volume_fix_is_not_applicable_twice() {
        let Some(image) = dump() else { return };
        let patches = patch::select(
            &VOLUME_FIX
                .iter()
                .map(|s| s.to_string())
                .collect::<Vec<String>>(),
        )
        .unwrap();
        let once = patch::apply_all(&image, &patches).unwrap();
        assert!(patch::apply_all(&once, &patches).is_err());
    }
}
