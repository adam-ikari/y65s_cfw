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

    /// Enable access to the firmware area.
    pub fn enable_firmware(&self) -> Result<()> {
        self.command(CMD_ENABLE_FIRMWARE, 0, 0)
    }

    /// Read `len` bytes starting at `addr` (address must be page aligned).
    pub fn read(&self, addr: usize, len: usize) -> Result<Vec<u8>> {
        if addr % PAGE_SIZE != 0 {
            return Err(Y65sError::BadInput("read address must be page aligned".into()));
        }
        self.enable_firmware()?;
        self.command(CMD_INIT_READ, (addr & 0xff) as u8, (addr >> 8) as u8)?;
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

    /// Erase the application area.
    pub fn erase(&self) -> Result<()> {
        self.enable_firmware()?;
        self.command(CMD_ERASE, 0, 0)?;
        Ok(())
    }

    /// Write `data` at `addr` (address must be page aligned).
    pub fn write(&self, addr: usize, data: &[u8]) -> Result<()> {
        if addr % PAGE_SIZE != 0 {
            return Err(Y65sError::BadInput("write address must be page aligned".into()));
        }
        self.enable_firmware()?;
        self.command(CMD_INIT_WRITE, (addr & 0xff) as u8, (addr >> 8) as u8)?;
        let mut done = 0usize;
        while done < data.len() {
            let take = (data.len() - done).min(PAGE_SIZE);
            let mut page = vec![0u8; PAGE_SIZE + 2];
            page[0] = REPORT_ID_XFER;
            page[1] = XFER_WRITE_PAGE;
            page[2..2 + take].copy_from_slice(&data[done..done + take]);
            self.xfer.send_feature(&page)?;
            done += take;
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
        let found = api.device_list().any(|d| {
            d.vendor_id() == 0x0603 && d.product_id() == 0x1020
        });
        if found {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    Err(Y65sError::Isp(
        "the keyboard did not come back as 0603:1020".into(),
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
}
