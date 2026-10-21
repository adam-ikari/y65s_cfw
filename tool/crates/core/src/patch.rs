//! Firmware patches: our custom firmware is the factory firmware plus a
//! reviewed set of byte level edits.
//!
//! Every patch carries the bytes it expects to find, so applying it to an
//! image that does not match fails loudly instead of silently corrupting the
//! flash.  Patches are the unit of review: one address, one intent.

use serde::{Deserialize, Serialize};

use crate::error::{Result, Y65sError};

/// One byte level change to the keyboard's firmware.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Patch {
    /// Stable identifier, used in the UI and in the brain notes.
    pub id: &'static str,
    /// What the patch does, in the operator's words.
    pub description: &'static str,
    /// Address in the keyboard's flash.
    pub address: u32,
    /// The bytes that must be there for the patch to apply.
    pub expect: &'static [u8],
    /// The bytes to write instead.
    pub replace: &'static [u8],
}

impl Patch {
    /// Does this patch apply to the given image?
    pub fn applies_to(&self, image: &[u8]) -> bool {
        let start = self.address as usize;
        let end = start + self.expect.len();
        if end > image.len() {
            return false;
        }
        image[start..end] == self.expect[..]
    }

    /// Apply the patch to a copy of the image.
    pub fn apply(&self, image: &[u8]) -> Result<Vec<u8>> {
        if !self.applies_to(image) {
            let start = self.address as usize;
            let end = (start + self.expect.len()).min(image.len());
            let actual: &[u8] = &image[start..end];
            return Err(Y65sError::BadInput(format!(
                "补丁 {} 不匹配：0x{start:04X} 处是 {:02X?}，期望 {:02X?}",
                self.id, actual, self.expect,
            )));
        }
        let mut out = image.to_vec();
        let start = self.address as usize;
        out[start..start + self.replace.len()].copy_from_slice(&self.replace);
        Ok(out)
    }
}

/// The patches we ship.
///
/// Each entry needs the address confirmed against the dump it targets; the
/// `expect` bytes are the safety net that keeps a stale patch from landing on
/// the wrong code.
pub const PATCHES: &[Patch] = &[
    Patch {
        id: "no-volume-send",
        description: "不发音量：去掉 8051 把 profile 音量字节(0x31) 转发给屏幕 SoC 的\
                      那一次拷贝，设置包里的音量字段从此不再被写入 => 屏幕拿不到音量，\
                      也就不会画那个与系统不一致的音量条。",
        address: 0x5557,
        // 90 0F 12 E0 90 0D BB F0
        //   MOV  DPTR,#0x0F12   ; 取 profile 的音量字段
        //   MOVX A,@DPTR
        //   MOV  DPTR,#0x0DBB   ; 设置包里的音量位置
        //   MOVX @DPTR,A
        expect: &[0x90, 0x0F, 0x12, 0xE0, 0x90, 0x0D, 0xBB, 0xF0],
        // 8 x NOP: 整段拷贝去掉
        replace: &[0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
    },
    Patch {
        id: "no-volume-send-zero",
        description: "同上，但把音量字段写成 0（静音）而不是不写。哪个让 SoC 真正\
                      不画音量条，刷一次看屏幕即可定。",
        address: 0x5557,
        expect: &[0x90, 0x0F, 0x12, 0xE0, 0x90, 0x0D, 0xBB, 0xF0],
        // 90 0D BB 74 00 F0 00 00
        replace: &[0x90, 0x0D, 0xBB, 0x74, 0x00, 0xF0, 0x00, 0x00],
    },
    Patch {
        id: "no-volume-ods",
        description: "旋钮不通知屏幕：音量旋钮在主控上（0x2812 采 P4.2/P0.7 正交解码，\
                      方向写进 xdata[0x0CA0]=9）。转到时主控同时做两件事：把 HID \
                      consumer 用量 0xE9/0xEA 写进 RAM 0x57/0x58（report id=2，\
                      16 位 consumer 页）发给主机，系统音量照常增减；再把状态字节\
                      0x81/0x82 写进 xdata[0x0EE4]，经 cmd 0x15 通知屏幕 SoC，屏幕\
                      据此画音量条。此补丁只去掉后半截：0x0EE4 不再写 0x81/0x82，旋钮\
                      分支直接跳到 0x05FA（跳过 cmd 0x15 发送与等应答，只保留运行记录\
                      发布）⇒ 屏幕不再画音量，主机侧音量指令不变。",
        address: 0x059C,
        // 旋钮分支 0x0594..0x05C3：
        //   059C: 90 0E E4 74 81 F0   MOV DPTR,#0x0EE4 / MOV A,#81 / MOVX @DPTR,A
        //   05A2: 78 57 76 E9         MOV R0,#57 / MOV @R0,#E9   ← HID consumer 用量
        //   05A6: 80 0F               SJMP 0x05B7
        //   05A8: EF 64 01 70 3A      MOV A,R7 / XRL A,#01 / JNZ 0x05E7
        //   05AD: 90 0E E4 74 82 F0   MOV DPTR,#0x0EE4 / MOV A,#82 / MOVX @DPTR,A
        //   05B3: 78 57 76 EA         MOV R0,#57 / MOV @R0,#EA   ← HID consumer 用量
        //   05B7: E4 08 F6 D2 0B D2 19 90 0E F2 F0
        //   05C2: 80 23               SJMP 0x05E7  ← cmd 0x15 发送 + 等应答
        expect: &[
            0x90, 0x0E, 0xE4, 0x74, 0x81, 0xF0, // 059C: 写 0x0EE4=0x81
            0x78, 0x57, 0x76, 0xE9, // 05A2: RAM 0x57 = 0xE9 (Volume Increment)
            0x80, 0x0F, // 05A6: SJMP 0x05B7
            0xEF, 0x64, 0x01, // 05A8: MOV A,R7 / XRL A,#01
            0x70, 0x3A, // 05AB: JNZ 0x05E7
            0x90, 0x0E, 0xE4, 0x74, 0x82, 0xF0, // 05AD: 写 0x0EE4=0x82
            0x78, 0x57, 0x76, 0xEA, // 05B3: RAM 0x57 = 0xEA (Volume Decrement)
            0xE4, 0x08, 0xF6, 0xD2, 0x0B, 0xD2, 0x19, // 05B7: RAM 0x58=0, BITS_0B, BITS_19
            0x90, 0x0E, 0xF2, 0xF0, // 05BE: [0x0EF2] = 0
            0x80, 0x23, // 05C2: SJMP 0x05E7
        ],
        replace: &[
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, // 059C: 不写 0x0EE4=0x81
            0x78, 0x57, 0x76, 0xE9, // 05A2: RAM 0x57 = 0xE9 (保留)
            0x80, 0x0F, // 05A6: SJMP 0x05B7
            0xEF, 0x64, 0x01, // 05A8: 保留
            0x70, 0x4D, // 05AB: JNZ 0x05FA
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, // 05AD: 不写 0x0EE4=0x82
            0x78, 0x57, 0x76, 0xEA, // 05B3: RAM 0x57 = 0xEA (保留)
            0xE4, 0x08, 0xF6, 0xD2, 0x0B, 0xD2, 0x19, // 05B7: 保留
            0x90, 0x0E, 0xF2, 0xF0, // 05BE: 保留
            0x80, 0x36, // 05C2: SJMP 0x05FA（跳过 cmd 0x15 发送）
        ],
    },
];

/// Result of checking a patch set against an image.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PatchReport {
    /// The patch that was checked.
    pub id: &'static str,
    /// Whether it applies to this image.
    pub applies: bool,
}

/// Check every patch against an image.
pub fn check(image: &[u8], patches: &[Patch]) -> Vec<PatchReport> {
    patches
        .iter()
        .map(|p| PatchReport {
            id: p.id,
            applies: p.applies_to(image),
        })
        .collect()
}

/// Apply a patch set to an image, failing on the first mismatch.
pub fn apply_all(image: &[u8], patches: &[&Patch]) -> Result<Vec<u8>> {
    let mut out = image.to_vec();
    for p in patches {
        out = p.apply(&out)?;
    }
    Ok(out)
}

/// Pick patches by id; unknown ids are an error.
pub fn select(ids: &[String]) -> Result<Vec<&'static Patch>> {
    ids.iter()
        .map(|id| {
            PATCHES
                .iter()
                .find(|p| p.id == id)
                .ok_or_else(|| Y65sError::BadInput(format!("没有这个补丁：{id}")))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn patch() -> Patch {
        Patch {
            id: "test",
            description: "example",
            address: 0x1000,
            expect: &[0xAA, 0xBB],
            replace: &[0xCC],
        }
    }

    #[test]
    fn applies_only_on_a_match() {
        let p = patch();
        let mut image = vec![0u8; 0x2000];
        image[0x1000] = 0xAA;
        image[0x1001] = 0xBB;
        assert!(p.applies_to(&image));
        image[0x1001] = 0x00;
        assert!(!p.applies_to(&image));
    }

    #[test]
    fn apply_writes_the_replacement() {
        let p = patch();
        let mut image = vec![0u8; 0x2000];
        image[0x1000] = 0xAA;
        image[0x1001] = 0xBB;
        let out = p.apply(&image).unwrap();
        assert_eq!(out[0x1000], 0xCC);
        assert_eq!(out[0x1001], 0xBB);
        // the original is untouched
        assert_eq!(image[0x1000], 0xAA);
    }

    #[test]
    fn apply_refuses_a_mismatch() {
        let p = patch();
        let image = vec![0u8; 0x2000];
        assert!(p.apply(&image).is_err());
    }

    #[test]
    fn check_lists_every_patch() {
        let reports = check(&vec![0u8; 0x2000], &[patch()]);
        assert_eq!(reports.len(), 1);
        assert!(!reports[0].applies);
    }

    /// The shipped patches must match the firmware dump they were written
    /// against, otherwise we would be patching the wrong bytes.
    #[test]
    fn shipped_patches_match_the_dumps() {
        let repo = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../firmware");
        let mut checked = 0;
        for dump in ["YD-Y65S_full.bin", "backups/YD-Y65S_full_20261019.bin"] {
            let path = repo.join(dump);
            let Ok(image) = std::fs::read(&path) else {
                continue;
            };
            for p in PATCHES {
                assert!(p.applies_to(&image), "补丁 {} 对不上 {dump}", p.id);
                checked += 1;
            }
        }
        assert!(checked > 0, "没有找到任何固件 dump，补丁无法被验证");
    }

    /// Applying the shipped patch must change exactly the expected bytes.
    #[test]
    fn shipped_patch_rewrites_only_the_volume_field() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../firmware/YD-Y65S_full.bin");
        let Ok(image) = std::fs::read(&path) else {
            return;
        };
        let p = &PATCHES[0];
        let out = p.apply(&image).unwrap();
        assert_ne!(out, image);
        // everything outside the patch must be untouched
        for i in 0..image.len() {
            if i < p.address as usize || i >= p.address as usize + p.replace.len() {
                assert_eq!(out[i], image[i], "补丁越界改了 0x{i:04X}");
            }
        }
    }

    /// Patches are picked by id; an unknown id is an error.
    #[test]
    fn select_picks_by_id() {
        let picked = select(&["no-volume-send".to_string()]).unwrap();
        assert_eq!(picked.len(), 1);
        assert_eq!(picked[0].id, "no-volume-send");
        assert!(select(&["没有这个补丁".to_string()]).is_err());
    }
    /// Two variants of the same patch share one address, so applying both must
    /// fail: the second one no longer matches the `expect` bytes.
    #[test]
    fn conflicting_variants_cannot_both_be_applied() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../firmware/YD-Y65S_full.bin");
        let Ok(image) = std::fs::read(&path) else {
            return;
        };
        let picked = select(&["no-volume-send".into(), "no-volume-send-zero".into()]).unwrap();
        assert!(apply_all(&image, &picked).is_err());
    }

    /// The knob patch must keep the host-facing consumer usage and drop only
    /// the module notification:
    ///
    /// * `0x05A2`/`0x05B3` write the HID consumer usage 0xE9/0xEA (Volume
    ///   Increment/Decrement) into RAM 0x57 -- that is what makes the host
    ///   change the system volume, so it has to survive.
    /// * the state byte 0x81/0x82 must no longer be written into 0x0EE4, or a
    ///   later cmd 0x15 would replay a stale "volume changed" event.
    /// * both exits of the knob branch must land on 0x05FA, which publishes
    ///   the runtime record; 0x05E7 is the cmd 0x15 send we want to skip.
    #[test]
    fn knob_patch_keeps_the_host_usage_and_drops_the_module_notify() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../firmware/YD-Y65S_full.bin");
        let Ok(image) = std::fs::read(&path) else {
            return;
        };
        let picked = select(&["no-volume-ods".into()]).unwrap();
        let out = picked[0].apply(&image).unwrap();
        let base = picked[0].address as usize;

        // host-facing consumer usage survives
        assert_eq!(&out[base + 0x06..base + 0x0A], &[0x78, 0x57, 0x76, 0xE9]);
        assert_eq!(&out[base + 0x17..base + 0x1B], &[0x78, 0x57, 0x76, 0xEA]);

        // the module state byte is no longer written
        assert!(
            !out[base..base + 40]
                .windows(6)
                .any(|w| w == [0x90, 0x0E, 0xE4, 0x74, 0x81, 0xF0]),
            "还在写 0x0EE4=0x81"
        );
        assert!(
            !out[base..base + 40]
                .windows(6)
                .any(|w| w == [0x90, 0x0E, 0xE4, 0x74, 0x82, 0xF0]),
            "还在写 0x0EE4=0x82"
        );

        // both branches jump to 0x05FA (publish), not 0x05E7 (cmd 0x15 send)
        assert_eq!(out[base + 0x0F], 0x70);
        assert_eq!(base + 0x11 + out[base + 0x10] as usize, 0x05FA);
        assert_eq!(out[base + 0x26], 0x80);
        assert_eq!(base + 0x28 + out[base + 0x27] as usize, 0x05FA);
    }

    /// The knob patch must not touch a single byte outside its own range.
    #[test]
    fn knob_patch_touches_nothing_outside_its_range() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../firmware/YD-Y65S_full.bin");
        let Ok(image) = std::fs::read(&path) else {
            return;
        };
        let picked = select(&["no-volume-ods".into()]).unwrap();
        let p = picked[0];
        let out = p.apply(&image).unwrap();
        let start = p.address as usize;
        let end = start + p.replace.len();
        for i in 0..image.len() {
            if i < start || i >= end {
                assert_eq!(out[i], image[i], "补丁越界改了 0x{i:04X}");
            }
        }
        assert_eq!(out[start..end], p.replace[..]);
    }
}
