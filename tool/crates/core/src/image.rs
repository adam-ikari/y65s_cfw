//! Image helpers: BMP -> the panel's pixel format.
//!
//! The module expects RGB565 **big endian** pixels, top row first, 240x135.

use std::path::Path;

use crate::error::{Result, Y65sError};
use crate::protocol::{SCREEN_H, SCREEN_W};

/// Convert a 24 or 32 bit uncompressed BMP into RGB565 big endian pixels.
pub fn bmp_to_rgb565be(path: &Path) -> Result<Vec<u8>> {
    let data = std::fs::read(path)?;
    bmp_bytes_to_rgb565be(&data)
}

/// Same as [`bmp_to_rgb565be`] but on an in-memory BMP.
pub fn bmp_bytes_to_rgb565be(data: &[u8]) -> Result<Vec<u8>> {
    if data.len() < 54 || &data[0..2] != b"BM" {
        return Err(Y65sError::BadInput("not a BMP file".into()));
    }
    let u16_at = |off: usize| -> u16 { u16::from_le_bytes([data[off], data[off + 1]]) };
    let u32_at = |off: usize| -> u32 {
        u32::from_le_bytes([data[off], data[off + 1], data[off + 2], data[off + 3]])
    };
    let pixel_off = u32_at(10) as usize;
    let width = i32::from_le_bytes([data[18], data[19], data[20], data[21]]) as i32;
    let height = i32::from_le_bytes([data[22], data[23], data[24], data[25]]) as i32;
    let bpp = u16_at(28);
    let compression = u32_at(30);
    if compression != 0 {
        return Err(Y65sError::BadInput("compressed BMPs are not supported".into()));
    }
    if bpp != 24 && bpp != 32 {
        return Err(Y65sError::BadInput(format!("{bpp} bit BMPs are not supported")));
    }
    let width = width.unsigned_abs() as usize;
    let height = height.unsigned_abs() as usize;
    let stride = ((width * (bpp as usize / 8)) + 3) & !3;
    let mut out = Vec::with_capacity(width * height * 2);
    for row in 0..height {
        let src_row = if height as i32 > 0 && i32::from_le_bytes([
            data[22], data[23], data[24], data[25],
        ]) > 0
        {
            row
        } else {
            height - 1 - row
        };
        let base = pixel_off + src_row * stride;
        for x in 0..width {
            let p = base + x * (bpp as usize / 8);
            if p + 2 >= data.len() {
                return Err(Y65sError::BadInput("truncated BMP".into()));
            }
            let b = data[p];
            let g = data[p + 1];
            let r = data[p + 2];
            let v = (((r as u16) & 0xF8) << 8) | (((g as u16) & 0xFC) << 3) | ((b as u16) & 0xF8);
            out.extend_from_slice(&v.to_be_bytes());
        }
    }
    Ok(out)
}

/// Convert a BMP and check that it matches the panel.
pub fn bmp_to_panel(data: &[u8]) -> Result<Vec<u8>> {
    let pixels = bmp_bytes_to_rgb565be(data)?;
    let want = SCREEN_W as usize * SCREEN_H as usize * 2;
    if pixels.len() != want {
        return Err(Y65sError::BadInput(format!(
            "image is {} bytes, the panel needs {want}",
            pixels.len()
        )));
    }
    Ok(pixels)
}

/// A frame filled with one colour.
pub fn solid_frame(rgb: (u8, u8, u8)) -> Vec<u8> {
    let v = (((rgb.0 as u16) & 0xF8) << 8) | (((rgb.1 as u16) & 0xFC) << 3) | ((rgb.2 as u16) & 0xF8);
    vec![v.to_be_bytes(); (SCREEN_W as usize) * (SCREEN_H as usize)]
        .into_iter()
        .flatten()
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Build a tiny uncompressed 24 bit BMP in memory.
    fn tiny_bmp(w: i32, h: i32) -> Vec<u8> {
        let stride = ((w as usize * 3) + 3) & !3;
        let pixels = (stride * h as usize) as u32;
        let mut d = vec![0u8; 54 + pixels as usize];
        d[0..2].copy_from_slice(b"BM");
        d[2..6].copy_from_slice(&(54u32 + pixels).to_le_bytes());
        d[10..14].copy_from_slice(&54u32.to_le_bytes());
        d[14..18].copy_from_slice(&40u32.to_le_bytes());
        d[18..22].copy_from_slice(&w.to_le_bytes());
        d[22..26].copy_from_slice(&h.to_le_bytes());
        d[26..28].copy_from_slice(&1u16.to_le_bytes());
        d[28..30].copy_from_slice(&24u16.to_le_bytes());
        d[30..34].copy_from_slice(&0u32.to_le_bytes());
        d[34..38].copy_from_slice(&pixels.to_le_bytes());
        // one red pixel
        d[54] = 0x00;
        d[55] = 0x00;
        d[56] = 0xFF;
        d
    }

    #[test]
    fn bmp_pixels_are_rgb565be() {
        let bmp = tiny_bmp(2, 2);
        let out = bmp_bytes_to_rgb565be(&bmp).unwrap();
        assert_eq!(out.len(), 2 * 2 * 2);
        // red 0xF800 big endian
        assert_eq!(&out[0..2], &[0xF8, 0x00]);
    }

    #[test]
    fn panel_check_rejects_wrong_size() {
        let bmp = tiny_bmp(4, 4);
        assert!(bmp_to_panel(&bmp).is_err());
    }

    #[test]
    fn solid_frame_has_the_panel_size() {
        let f = solid_frame((0, 0, 0));
        assert_eq!(f.len(), SCREEN_W as usize * SCREEN_H as usize * 2);
    }
}
