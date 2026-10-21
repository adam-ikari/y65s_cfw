//! Core of the YD-Y65S toolchain: the vendor protocol, the HID transport,
//! the ISP (flash) layer and the key map reference.
//!
//! The crate has no UI dependencies so it can be used from the Tauri app,
//! from a CLI or from tests.

pub mod error;
pub mod hid;
pub mod isp;
pub mod keys;
pub mod patch;
pub mod protocol;

pub use error::{Result, Y65sError};
pub use hid::{Collection, DeviceInfo};
pub use protocol::{
    build_record, record, record_with_sub, sub_offset, ClockPayload, ClockRoute, Profile,
    ProfileField, ScreenTiming, CLOCK_ROUTES, DATA_OFF, FACTORY_PROFILE_OFF, LED_EFFECT_INDEX,
    LED_EFFECT_MODE, LIVE_PROFILE_OFF, PAYLOAD, PID, PROFILE_FIELDS, PROFILE_LEN,
    PROFILE_MARKER, REPORT, SCREEN_BLOCK, SCREEN_H, SCREEN_W, USAGE, USAGE_PAGE, VID,
    VOLUME_LEVEL,
};

use std::time::Duration;

use hid::Collection as HidCollection;
use time::OffsetDateTime;

/// A connected keyboard.
pub struct Keyboard {
    vendor: HidCollection,
}

impl Keyboard {
    /// Connect to the keyboard's vendor collection.
    pub fn open() -> Result<Self> {
        Ok(Self {
            vendor: HidCollection::vendor()?,
        })
    }

    /// Which backend we ended up using ("hidapi" or "vendorhid(win32)").
    pub fn backend(&self) -> &'static str {
        "hidapi"
    }

    /// Send a record on the vendor channel.
    pub fn send_record(&self, record: &[u8]) -> Result<()> {
        let mut packet = Vec::with_capacity(record.len() + 1);
        packet.push(REPORT);
        packet.extend_from_slice(record);
        self.vendor.send_feature(&packet)
    }

    /// Send a record and wait for the answer frame.
    pub fn command(
        &self,
        cmd: u8,
        data: &[u8],
        at: usize,
        sub: Option<u8>,
        wait: Duration,
    ) -> Result<(bool, Vec<u8>)> {
        let rec = record_with_sub(cmd, data, at, sub);
        self.send_record(&rec)?;
        let frame = self.vendor.read_input(wait).unwrap_or_default();
        Ok((true, frame))
    }

    /// Write the device profile (module command 0x52).
    pub fn write_profile(&self, profile: &Profile) -> Result<Vec<u8>> {
        let mut prof = profile.bytes().to_vec();
        prof[0x7E..0x80].copy_from_slice(&PROFILE_MARKER);
        self.send_record(&build_record(record::PROFILE, &prof, DATA_OFF, None))?;
        Ok(prof)
    }

    /// Set the clock, trying every route we know.
    ///
    /// Each route gets a different minute so the screen tells us which one
    /// was accepted.
    pub fn set_clock_sweep(&self, base: OffsetDateTime) -> Result<Vec<ClockAttempt>> {
        let mut out = Vec::new();
        for (i, route) in CLOCK_ROUTES.iter().enumerate() {
            let when = base + time::Duration::minutes(i as i64);
            let payload = clock_payload_for(when);
            let rec = record_with_sub(route.record, &payload, route.at, route.sub);
            self.send_record(&rec)?;
            let frame = self.vendor.read_input(Duration::from_millis(800)).unwrap_or_default();
            out.push(ClockAttempt {
                route: *route,
                time: format!("{:02}:{:02}", when.hour(), when.minute()),
                answer: frame,
            });
            std::thread::sleep(Duration::from_millis(250));
        }
        Ok(out)
    }
}

/// One clock delivery attempt.
#[derive(Debug, Clone, serde::Serialize)]
pub struct ClockAttempt {
    /// The route that was used.
    pub route: ClockRoute,
    /// The time that was sent.
    pub time: String,
    /// The answer frame we got back.
    pub answer: Vec<u8>,
}

/// Build the vendor clock payload for a given time.
pub fn clock_payload_for(when: OffsetDateTime) -> [u8; 11] {
    use time::Weekday;
    let weekday = match when.weekday() {
        Weekday::Sunday => 0,
        Weekday::Monday => 1,
        Weekday::Tuesday => 2,
        Weekday::Wednesday => 3,
        Weekday::Thursday => 4,
        Weekday::Friday => 5,
        Weekday::Saturday => 6,
    };
    ClockPayload::new(
        when.year() as u16,
        when.month() as u8,
        when.day(),
        when.hour() as u8,
        when.minute() as u8,
        when.second() as u8,
        weekday,
    )
    .to_bytes()
}
