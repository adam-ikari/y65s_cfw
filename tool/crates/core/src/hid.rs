//! Cross platform HID transport.
//!
//! One code path for Windows (hid.dll), Linux (/dev/hidrawN) and macOS
//! (IOHIDManager) via the `hidapi` crate.  The keyboard exposes several HID
//! collections; we need two of them:
//!
//! * usage page 0xff02 / usage 0x0002 -- the vendor command channel
//!   (feature report 9, the 519 byte record protocol).
//! * usage page 0xff00 / usage 0x0001 -- the ISP channel (feature reports 5
//!   and 6), used to read and write the keyboard's flash.

use std::sync::mpsc::{self, RecvTimeoutError};
use std::thread;
use std::time::Duration;

use hidapi::{HidApi, HidDevice};

use crate::error::{Result, Y65sError};
use crate::protocol::{USAGE, USAGE_PAGE, VID, PID};

/// A HID collection of the keyboard.
pub struct Collection {
    device: HidDevice,
    path: std::ffi::CString,
    label: String,
}

impl Collection {
    /// Open the collection with the given usage page and usage.
    pub fn open(usage_page: u16, usage: u16) -> Result<Self> {
        let api = HidApi::new().map_err(|e| Y65sError::Open(e.to_string()))?;
        let wanted = api
            .device_list()
            .filter(|d| d.vendor_id() == VID && d.product_id() == PID)
            .find(|d| d.usage_page() == usage_page && d.usage() == usage)
            .ok_or_else(|| {
                Y65sError::DeviceNotFound(format!(
                    "usage page 0x{usage_page:04x} / usage 0x{usage:04x} \
                     of {VID:04x}:{PID:04x}"
                ))
            })?;
        let path = wanted.path().to_owned();
        let device = api
            .open_path(&path)
            .map_err(|e| Y65sError::Open(format!("{}: {e}", path.to_string_lossy())))?;
        Ok(Self {
            device,
            path,
            label: format!("{usage_page:04x}:{usage:04x}"),
        })
    }

    /// Open the vendor command collection.
    pub fn vendor() -> Result<Self> {
        Self::open(USAGE_PAGE, USAGE)
    }

    /// Open the ISP collection.
    pub fn isp() -> Result<Self> {
        Self::open(0xFF00, 0x0001)
    }

    /// Send a feature report; `data` includes the report id in byte 0.
    pub fn send_feature(&self, data: &[u8]) -> Result<()> {
        self.device
            .send_feature_report(data)
            .map_err(|e| Y65sError::Transfer(format!("{}: {e}", self.label)))?;
        Ok(())
    }

    /// Read a feature report; returns the raw buffer (report id first).
    pub fn get_feature(&self, length: usize) -> Result<Vec<u8>> {
        let mut buf = vec![0u8; length];
        let n = self
            .device
            .get_feature_report(&mut buf)
            .map_err(|e| Y65sError::Transfer(format!("{}: {e}", self.label)))?;
        buf.truncate(n);
        Ok(buf)
    }

    /// Best effort read of an input report with a timeout.
    ///
    /// `hidapi` has no timeout on `read`, so the read happens on a helper
    /// thread.  On Linux the kernel hid driver may swallow the interrupt
    /// endpoint; feature reports (what we actually need) always work.
    pub fn read_input(&self, timeout: Duration) -> Option<Vec<u8>> {
        let (tx, rx) = mpsc::channel();
        let path = self.path.clone();
        thread::spawn(move || {
            let Ok(api) = hidapi::HidApi::new() else { return };
            let Ok(mut device) = api.open_path(&path) else { return };
            let mut buf = [0u8; 64];
            if let Ok(n) = device.read(&mut buf) {
                let _ = tx.send(buf[..n].to_vec());
            }
        });
        match rx.recv_timeout(timeout) {
            Ok(v) => Some(v),
            Err(RecvTimeoutError::Timeout) => None,
            Err(RecvTimeoutError::Disconnected) => None,
        }
    }
}

/// Everything we can see of the keyboard.
#[derive(Debug, Clone, serde::Serialize)]
pub struct DeviceInfo {
    /// Vendor id.
    pub vid: u16,
    /// Product id.
    pub pid: u16,
    /// Product string, when the backend exposes it.
    pub product: Option<String>,
    /// Usage page of the collection.
    pub usage_page: u16,
    /// Usage of the collection.
    pub usage: u16,
}

/// List the keyboard's HID collections.
pub fn list_collections() -> Result<Vec<DeviceInfo>> {
    let api = HidApi::new().map_err(|e| Y65sError::Open(e.to_string()))?;
    Ok(api
        .device_list()
        .filter(|d| d.vendor_id() == VID && d.product_id() == PID)
        .map(|d| DeviceInfo {
            vid: d.vendor_id(),
            pid: d.product_id(),
            product: d.product_string().map(|s| s.to_string()),
            usage_page: d.usage_page(),
            usage: d.usage(),
        })
        .collect())
}

#[cfg(test)]
mod tests {
    #[test]
    fn listing_never_panics() {
        // No device in CI: the call must fail gracefully.
        let _ = super::list_collections();
    }
}
