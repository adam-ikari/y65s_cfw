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
            return Err(Y65sError::BadInput(format!(
                "补丁 {} 不匹配：0x{start:04X} 处是 {:02X?}，期望 {:02X?}",
                self.id,
                &image[start..end],
                &self.expect,
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
        id: "no-volume-display",
        description: "不再把音量显示到屏幕：8051 侧把 profile 的音量字节(0x31) \
                       转发给屏幕 SoC 的那一次拷贝，改成写 0xFF（超出 0~100 量程，\
                       SoC 无法显示音量条）。没有我们的软件在跑时，屏幕上就不会出现\
                       与系统不一致的音量；需要显示时由我们自己的推帧负责。",
        address: 0x5557,
        // 90 0F 12 E0 90 0D BB F0
        //   MOV  DPTR,#0x0F12   ; 取 profile 的音量字段
        //   MOVX A,@DPTR
        //   MOV  DPTR,#0x0DBB   ; 设置包里的音量位置
        //   MOVX @DPTR,A
        expect: &[0x90, 0x0F, 0x12, 0xE0, 0x90, 0x0D, 0xBB, 0xF0],
        // 90 0D BB 74 FF F0 00 00
        //   MOV  DPTR,#0x0DBB
        //   MOV  A,#0xFF
        //   MOVX @DPTR,A
        //   NOP NOP
        replace: &[0x90, 0x0D, 0xBB, 0x74, 0xFF, 0xF0, 0x00, 0x00],
    },
    Patch {
        id: "no-volume-display-zero",
        description: "同 no-volume-display，但哨兵值用 0x00 而不是 0xFF。\
                      哪个值让 SoC 真正不画音量条，刷一次看屏幕即可定。",
        address: 0x5557,
        expect: &[0x90, 0x0F, 0x12, 0xE0, 0x90, 0x0D, 0xBB, 0xF0],
        // 90 0D BB 74 00 F0 00 00
        replace: &[0x90, 0x0D, 0xBB, 0x74, 0x00, 0xF0, 0x00, 0x00],
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
pub fn apply_all(image: &[u8], patches: &[Patch]) -> Result<Vec<u8>> {
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
        let repo = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../firmware");
        let mut checked = 0;
        for dump in ["YD-Y65S_full.bin", "backups/YD-Y65S_full_20261019.bin"] {
            let path = repo.join(dump);
            let Ok(image) = std::fs::read(&path) else {
                continue;
            };
            for p in PATCHES {
                assert!(
                    p.applies_to(&image),
                    "补丁 {} 对不上 {dump}",
                    p.id
                );
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
        let Ok(image) = std::fs::read(&path) else { return };
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
}
