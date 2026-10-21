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
    pub id: String,
    /// What the patch does, in the operator's words.
    pub description: String,
    /// Address in the keyboard's flash.
    pub address: u32,
    /// The bytes that must be there for the patch to apply.
    pub expect: Vec<u8>,
    /// The bytes to write instead.
    pub replace: Vec<u8>,
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
pub const PATCHES: &[Patch] = &[];

/// Result of checking a patch set against an image.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PatchReport {
    /// The patch that was checked.
    pub id: String,
    /// Whether it applies to this image.
    pub applies: bool,
}

/// Check every patch against an image.
pub fn check(image: &[u8], patches: &[Patch]) -> Vec<PatchReport> {
    patches
        .iter()
        .map(|p| PatchReport {
            id: p.id.clone(),
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

#[cfg(test)]
mod tests {
    use super::*;

    fn patch() -> Patch {
        Patch {
            id: "test".into(),
            description: "example".into(),
            address: 0x1000,
            expect: vec![0xAA, 0xBB],
            replace: vec![0xCC],
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
}
