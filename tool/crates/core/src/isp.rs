//! The Sinowealth ISP: read and write the keyboard's flash.
//!
//! Protocol (identical to the `sinowisp` tool, reimplemented here so the
//! tool works on every platform without an external binary):
//!
//! * command channel: feature report 5 on usage page 0xff00, 6 bytes
//!   `[0x05, cmd, arg0, arg1, 0, 0]`
//! * transfer channel: feature report 6, carrying one 2048 byte page
//! * commands: 0x55 enable firmware, 0x52 init read, 0x45 erase,
//!   0x57 init write, 0x5a reboot
//!
//! Entering the ISP from the application: feature report 5 with the magic
//! `[0x05, 0x75, 0, 0, 0, 0]`.  The board re-enumerates as 0603:1020 and
//! the ISP collection is then the only one available.
//!
//! # The write order matters
//!
//! Writing an image is **erase → init write → pages → enable → reboot**.
//! The `enable` (0x55) has to come *after* the pages: the bootloader rebuilds
//! the jump instruction at 0x0000 from the reset vector it stored at
//! `0xEFFC` and sets the `0xEFFB = 0x02` marker that tells it a firmware is
//! present.  Enabling first -- which an earlier version of this file did --
//! leaves the board unable to boot.  [`write_plan`] is the single place that
//! order is spelled out, and a unit test keeps it that way.

use std::time::Duration;

use crate::error::{Result, Y65sError};
use crate::hid::Collection;
use crate::protocol::{PID, VID};

/// Size of one flash page.
pub const PAGE_SIZE: usize = 2048;
/// Size of the application area.
pub const FIRMWARE_SIZE: usize = 0xF000;
/// Size of the whole flash.
pub const FLASH_SIZE: usize = 0x10000;

/// Report id of the ISP command channel.
const REPORT_ID_CMD: u8 = 0x05;
/// Report id of the ISP transfer channel.
const REPORT_ID_XFER: u8 = 0x06;

/// Command: enable access to the firmware area.
const CMD_ENABLE_FIRMWARE: u8 = 0x55;
/// Command: start a read at the given address.
const CMD_INIT_READ: u8 = 0x52;
/// Command: start a write at the given address.
const CMD_INIT_WRITE: u8 = 0x57;
/// Command: erase the application area.
const CMD_ERASE: u8 = 0x45;
/// Command: reboot into the application.
const CMD_REBOOT: u8 = 0x5a;

/// Transfer marker for a read page.
const XFER_READ_PAGE: u8 = 0x72;
/// Transfer marker for a write page.
const XFER_WRITE_PAGE: u8 = 0x77;

/// The magic that makes the application jump into the ISP.
pub const ENTER_ISP_MAGIC: [u8; 6] = [0x05, 0x75, 0x00, 0x00, 0x00, 0x00];

/// Where the bootloader keeps the canonical copy of the reset vector.
const VECTOR_COPY: usize = FIRMWARE_SIZE - 4;
/// The enable marker right in front of it.
const VECTOR_MARKER: usize = FIRMWARE_SIZE - 5;

/// The bytes the bootloader owns: the enable marker and the reset vector
/// copy.  They are not ours to compare after a write.
pub fn bootloader_window() -> std::ops::Range<usize> {
    VECTOR_MARKER..FIRMWARE_SIZE
}

/// One step of the ISP write sequence.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Step {
    /// 0x45 -- erase the application area.
    Erase,
    /// 0x57 -- start writing at the given address.
    InitWrite(u16),
    /// 0x77 -- one 2048 byte page.
    WritePage,
    /// 0x55 -- enable the firmware that was just written.
    Enable,
    /// 0x5a -- reboot into the application.
    Reboot,
}

/// The order the bootloader needs for a full write.
///
/// `enable` comes after the pages, never before the erase -- see the module
/// documentation.
pub fn write_plan(pages: usize) -> Vec<Step> {
    let mut plan = Vec::with_capacity(pages + 4);
    plan.push(Step::Erase);
    plan.push(Step::InitWrite(0));
    for _ in 0..pages {
        plan.push(Step::WritePage);
    }
    plan.push(Step::Enable);
    plan.push(Step::Reboot);
    plan
}

/// Prepare the bytes we are going to send.
///
/// The vendor tool keeps the application reset vector in two places: the
/// jump instruction at 0x0000 and a canonical copy at `0xEFFC`
/// (`firmware_size - 4`).  It mirrors the second one into the payload before
/// writing; we do the same, byte for byte.
pub fn prepare_payload(image: &[u8]) -> Result<Vec<u8>> {
    if image.len() < FIRMWARE_SIZE {
        return Err(Y65sError::BadInput(format!(
            "镜像太小：{} 字节，至少需要 {FIRMWARE_SIZE} 字节",
            image.len()
        )));
    }
    let mut payload = image[..FIRMWARE_SIZE].to_vec();
    let vector: [u8; 2] = [payload[1], payload[2]];
    payload[VECTOR_COPY..VECTOR_COPY + 2].copy_from_slice(&vector);
    Ok(payload)
}

/// Compare a flash read-back with the image we meant to write.
///
/// The bootloader owns the marker byte and the vector copy, so those four
/// bytes are skipped; everything else has to match exactly.
pub fn verify_image(image: &[u8], readback: &[u8]) -> Result<()> {
    let window = bootloader_window();
    let n = image.len().min(readback.len()).min(FIRMWARE_SIZE);
    for i in 0..n {
        if window.contains(&i) {
            continue;
        }
        if image[i] != readback[i] {
            return Err(Y65sError::Isp(format!(
                "读回校验失败：0x{i:04X} 期望 {:02X}，实得 {:02X}",
                image[i], readback[i]
            )));
        }
    }
    Ok(())
}

/// An ISP session.
pub struct Isp {
    cmd: Collection,
    xfer: Collection,
}

impl Isp {
    /// Open the ISP channels (the device must already be in ISP mode).
    pub fn open() -> Result<Self> {
        // The ISP collection carries both report 5 and report 6, so one open
        // is enough; a second handle keeps the API simple and works on
        // backends that dislike sharing a handle between threads.
        let cmd = Collection::open(0xFF00, 0x0001)?;
        let xfer = Collection::open(0xFF00, 0x0001)?;
        Ok(Self { cmd, xfer })
    }

    fn command(&self, cmd: u8, arg0: u8, arg1: u8) -> Result<()> {
        let packet = [REPORT_ID_CMD, cmd, arg0, arg1, 0x00, 0x00];
        self.cmd.send_feature(&packet)
    }

    /// Send a command without caring whether the call reported an error.
    ///
    /// The board leaves the bus while the command is in flight, so
    /// `SetFeature` usually comes back with an error (0x1f) even though the
    /// command was accepted and the jump/reboot happened.  That failure is
    /// the *expected* sign of success, so the command channel is best effort;
    /// a real failure shows up on the transfer channel, where the pages are
    /// written and read back.
    fn command_best_effort(&self, cmd: u8, arg0: u8, arg1: u8) {
        let packet = [REPORT_ID_CMD, cmd, arg0, arg1, 0x00, 0x00];
        let _ = self.cmd.send_feature(&packet);
    }

    /// Enable access to the firmware area.
    pub fn enable_firmware(&self) -> Result<()> {
        self.command(CMD_ENABLE_FIRMWARE, 0, 0)
    }

    /// Read `len` bytes starting at `addr` (address must be page aligned).
    pub fn read(&self, addr: usize, len: usize) -> Result<Vec<u8>> {
        if addr % PAGE_SIZE != 0 {
            return Err(Y65sError::BadInput("read address must be page aligned".into()));
        }
        self.command_best_effort(CMD_ENABLE_FIRMWARE, 0, 0);
        std::thread::sleep(Duration::from_millis(200));
        self.command_best_effort(CMD_INIT_READ, (addr & 0xff) as u8, (addr >> 8) as u8);
        std::thread::sleep(Duration::from_millis(200));
        let mut out = Vec::with_capacity(len);
        while out.len() < len {
            let mut buf = vec![0u8; PAGE_SIZE + 2];
            buf[0] = REPORT_ID_XFER;
            let raw = self.xfer.get_feature(PAGE_SIZE + 2)?;
            if raw.len() < 2 {
                return Err(Y65sError::BadAnswer("short ISP page".into()));
            }
            if raw[1] != XFER_READ_PAGE {
                return Err(Y65sError::BadAnswer(format!(
                    "unexpected ISP marker 0x{:02x}",
                    raw[1]
                )));
            }
            let take = (len - out.len()).min(PAGE_SIZE);
            out.extend_from_slice(&raw[2..2 + take]);
        }
        Ok(out)
    }

    /// Write one page.  Callers should use [`Isp::flash_image`], which gets
    /// the command order right.
    fn write_page(&self, data: &[u8]) -> Result<()> {
        let mut page = vec![0u8; PAGE_SIZE + 2];
        page[0] = REPORT_ID_XFER;
        page[1] = XFER_WRITE_PAGE;
        page[2..2 + data.len()].copy_from_slice(data);
        self.xfer.send_feature(&page)
    }

    /// Write a whole image: erase, write every page, enable, reboot.
    ///
    /// This is the only write path the tool uses.  It follows [`write_plan`]
    /// exactly, so the enable always lands after the pages.
    pub fn flash_image(&self, image: &[u8]) -> Result<()> {
        let payload = prepare_payload(image)?;
        let pages = payload.len().div_ceil(PAGE_SIZE);
        let mut page_index = 0usize;
        for step in write_plan(pages) {
            match step {
                Step::Erase => {
                    self.command(CMD_ERASE, 0, 0)?;
                    std::thread::sleep(Duration::from_millis(2000));
                }
                Step::InitWrite(addr) => {
                    self.command(CMD_INIT_WRITE, (addr & 0xff) as u8, (addr >> 8) as u8)?;
                    std::thread::sleep(Duration::from_millis(200));
                }
                Step::WritePage => {
                    let start = page_index * PAGE_SIZE;
                    let end = (start + PAGE_SIZE).min(payload.len());
                    self.write_page(&payload[start..end])?;
                    page_index += 1;
                }
                Step::Enable => {
                    self.command(CMD_ENABLE_FIRMWARE, 0, 0)?;
                    std::thread::sleep(Duration::from_millis(500));
                }
                Step::Reboot => self.command(CMD_REBOOT, 0, 0)?,
            }
        }
        Ok(())
    }

    /// Reboot into the application.
    pub fn reboot(&self) -> Result<()> {
        self.command(CMD_REBOOT, 0, 0)?;
        Ok(())
    }
}

/// Ask the running application to jump into the ISP.
pub fn enter_isp() -> Result<()> {
    let cmd = Collection::open(0xFF00, 0x0001)?;
    cmd.send_feature(&ENTER_ISP_MAGIC)?;
    std::thread::sleep(Duration::from_millis(600));
    Ok(())
}

/// Wait until the keyboard shows up as the ISP device (0603:1020).
pub fn wait_for_isp(timeout: Duration) -> Result<()> {
    let deadline = std::time::Instant::now() + timeout;
    while std::time::Instant::now() < deadline {
        let api = hidapi::HidApi::new().map_err(|e| Y65sError::Open(e.to_string()))?;
        let found = api
            .device_list()
            .any(|d| d.vendor_id() == ISP_VID && d.product_id() == ISP_PID);
        if found {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    Err(Y65sError::Isp(
        "the keyboard did not come back as 0603:1020".into(),
    ))
}

/// Wait until the keyboard is back in application mode (258a:019d).
pub fn wait_for_app(timeout: Duration) -> Result<()> {
    let deadline = std::time::Instant::now() + timeout;
    while std::time::Instant::now() < deadline {
        let api = hidapi::HidApi::new().map_err(|e| Y65sError::Open(e.to_string()))?;
        let found = api
            .device_list()
            .any(|d| d.vendor_id() == VID && d.product_id() == PID);
        if found {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    Err(Y65sError::Isp(
        "the keyboard did not come back as 258a:019d".into(),
    ))
}

/// The ids the keyboard uses in ISP mode.
pub const ISP_VID: u16 = 0x0603;
/// The ids the keyboard uses in ISP mode.
pub const ISP_PID: u16 = 0x1020;

/// Re-exported for convenience.
pub const APP_VID: u16 = VID;
/// Re-exported for convenience.
pub const APP_PID: u16 = PID;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sizes_are_consistent() {
        assert_eq!(FIRMWARE_SIZE % PAGE_SIZE, 0);
        // the ISP bootloader lives in the last 4 KiB and is never written
        assert_eq!(FLASH_SIZE - FIRMWARE_SIZE, 2 * PAGE_SIZE);
    }

    /// The enable command must never precede the pages: that is what bricked
    /// a keyboard when this file still enabled before erasing.
    #[test]
    fn enable_comes_after_the_pages() {
        let plan = write_plan(30);
        let enable = plan
            .iter()
            .position(|s| *s == Step::Enable)
            .expect("no enable step");
        let last_page = plan
            .iter()
            .rposition(|s| *s == Step::WritePage)
            .expect("no page step");
        assert!(enable > last_page, "enable 必须排在所有写页之后");
        assert_eq!(plan[0], Step::Erase);
        assert_eq!(*plan.last().unwrap(), Step::Reboot);
        assert_eq!(
            plan.iter().filter(|s| **s == Step::WritePage).count(),
            30
        );
    }

    /// The payload keeps the reset vector twice, exactly like the vendor
    /// tool writes it.
    #[test]
    fn payload_mirrors_the_reset_vector() {
        let mut image = vec![0u8; FIRMWARE_SIZE];
        image[0] = 0x02;
        image[1] = 0x89;
        image[2] = 0xd7;
        let payload = prepare_payload(&image).unwrap();
        assert_eq!(&payload[VECTOR_COPY..VECTOR_COPY + 2], &[0x89, 0xd7]);
        assert_eq!(&payload[1..3], &[0x89, 0xd7]);
    }

    #[test]
    fn a_short_image_is_refused() {
        assert!(prepare_payload(&[0u8; 16]).is_err());
    }

    /// The bootloader owns the marker and the vector copy, so the read-back
    /// check has to skip them -- but nothing else.
    #[test]
    fn verification_skips_only_the_bootloader_window() {
        let mut image = vec![0u8; FIRMWARE_SIZE];
        let mut readback = image.clone();
        readback[VECTOR_MARKER] = 0x02;
        readback[VECTOR_COPY] = 0x89;
        readback[VECTOR_COPY + 1] = 0xd7;
        assert!(verify_image(&image, &readback).is_ok());
        readback[0x1000] = 0xff;
        assert!(verify_image(&image, &readback).is_err());
    }
}
