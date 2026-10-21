//! The YD-Y65S vendor protocol, as we reverse engineered it.
//!
//! The keyboard is a USB HID composite.  The interesting collection is the
//! vendor one (usage page 0xff02 / usage 0x0002) which carries feature
//! report 9: a 519 byte record whose first byte selects the handler and whose
//! data window starts at byte 7.
//!
//! ```text
//! payload[0]      record command
//! payload[1]      sub-dispatch (record 0x03) / module command index (0x05)
//! payload[7..]    data window
//! ```

use serde::{Deserialize, Serialize};

use crate::error::{Result, Y65sError};

/// USB vendor id of the keyboard.
pub const VID: u16 = 0x258A;
/// USB product id of the keyboard.
pub const PID: u16 = 0x019D;
/// Usage page of the vendor collection.
pub const USAGE_PAGE: u16 = 0xFF02;
/// Usage of the vendor collection.
pub const USAGE: u16 = 0x0002;
/// Feature report id of the vendor command channel.
pub const REPORT: u8 = 9;
/// Length of the vendor command payload (excluding the report id).
pub const PAYLOAD: usize = 519;
/// Offset of the data window inside a record.
pub const DATA_OFF: usize = 7;

/// The profile (module command 0x52) is 128 bytes.
pub const PROFILE_LEN: usize = 128;
/// Offset of the factory profile inside the keyboard's flash.
pub const FACTORY_PROFILE_OFF: usize = 0x9983;
/// Offset of the live profile inside the keyboard's flash.
pub const LIVE_PROFILE_OFF: usize = 0xA400;
/// The "profile initialised" marker at the end of the profile.
pub const PROFILE_MARKER: [u8; 2] = [0x5A, 0xA5];

/// Screen geometry of the YD-Y65S panel (landscape).
pub const SCREEN_W: u16 = 240;
/// Screen height.
pub const SCREEN_H: u16 = 135;
/// Bytes per `AccessData_Page` block.
pub const SCREEN_BLOCK: usize = 512;

/// Record commands we know.
pub mod record {
    /// Sub-dispatch 1..4, mapping to module commands 0x62/0x66/0x6A/0x5E.
    pub const SUB_DISPATCH: u8 = 0x03;
    /// 128 byte window, forwarded as module command 0x52 (the device profile).
    pub const PROFILE: u8 = 0x04;
    /// 512 byte window, forwarded as module command 0x6E + payload[4].
    pub const WINDOW: u8 = 0x05;
    /// TFT mode setup, module command 0x56.
    pub const TFT_MODE: u8 = 0x06;
    /// RAM config table.  **Writes the keyboard's flash** -- never send casually.
    pub const RAM_CONFIG: u8 = 0x08;
    /// Fixed code table, module command 0x54.
    pub const CODE_TABLE: u8 = 0x0A;
    /// Start of a screen transfer (`SetGIFParam`).
    pub const GIF_PARAM: u8 = 0x0D;
    /// One screen page (`AccessData_Page`).
    pub const ACCESS_PAGE: u8 = 0x0C;
    /// End of a screen transfer.
    pub const GIF_END: u8 = 0x0D;
}

/// The fields of the device profile we understand.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProfileField {
    /// Byte offset inside the 128 byte profile.
    pub offset: u8,
    /// Human readable name.
    pub name: &'static str,
    /// Value in the factory profile.
    pub factory: u8,
}

/// The profile fields we know about.
pub const PROFILE_FIELDS: &[ProfileField] = &[
    ProfileField {
        offset: 0x03,
        name: "keymap_id",
        factory: 0x00,
    },
    ProfileField {
        offset: 0x0A,
        name: "led_effect_index",
        factory: 0x0B,
    },
    ProfileField {
        offset: 0x16,
        name: "reserved_16",
        factory: 0x00,
    },
    ProfileField {
        offset: 0x18,
        name: "reserved_18",
        factory: 0x99,
    },
    ProfileField {
        offset: 0x1F,
        name: "reserved_1F",
        factory: 0x0A,
    },
    ProfileField {
        offset: 0x31,
        name: "volume_level",
        factory: 0x64,
    },
    ProfileField {
        offset: 0x33,
        name: "led_effect_mode",
        factory: 0x01,
    },
    ProfileField {
        offset: 0x35,
        name: "reserved_35",
        factory: 0x01,
    },
    ProfileField {
        offset: 0x36,
        name: "reserved_36",
        factory: 0x01,
    },
    ProfileField {
        offset: 0x37,
        name: "reserved_37",
        factory: 0x00,
    },
];

/// Offset of the lighting effect index inside the profile.
pub const LED_EFFECT_INDEX: u8 = 0x0A;
/// Offset of the lighting effect mode inside the profile.
pub const LED_EFFECT_MODE: u8 = 0x33;
/// Offset of the volume level inside the profile.
pub const VOLUME_LEVEL: u8 = 0x31;

/// Build one record for the vendor command channel.
pub fn build_record(cmd: u8, data: &[u8], at: usize, sub: Option<(u8, usize)>) -> Vec<u8> {
    let mut p = vec![0u8; PAYLOAD];
    p[0] = cmd;
    if let Some((value, where_)) = sub {
        p[where_] = value & 0x07;
    }
    if !data.is_empty() {
        let end = (at + data.len()).min(PAYLOAD);
        if at < end {
            p[at..end].copy_from_slice(&data[..end - at]);
        }
    }
    p
}

/// Where the sub-dispatch byte of a record lives.
pub fn sub_offset(cmd: u8) -> Option<usize> {
    match cmd {
        record::SUB_DISPATCH => Some(1),
        record::WINDOW => Some(4),
        _ => None,
    }
}

/// Build a record with the sub-dispatch handled for you.
pub fn record_with_sub(cmd: u8, data: &[u8], at: usize, sub: Option<u8>) -> Vec<u8> {
    build_record(
        cmd,
        data,
        at,
        sub.map(|v| (v, sub_offset(cmd).unwrap_or(1))),
    )
}

/// Extract the factory profile from a flash dump.
pub fn factory_profile(dump: &[u8]) -> Result<&[u8]> {
    dump.get(FACTORY_PROFILE_OFF..FACTORY_PROFILE_OFF + PROFILE_LEN)
        .ok_or_else(|| Y65sError::BadInput("flash dump is too small".into()))
}

/// Extract the live profile from a flash dump.
pub fn live_profile(dump: &[u8]) -> Result<&[u8]> {
    dump.get(LIVE_PROFILE_OFF..LIVE_PROFILE_OFF + PROFILE_LEN)
        .ok_or_else(|| Y65sError::BadInput("flash dump is too small".into()))
}

/// A decoded profile: the raw bytes plus the fields we know.
#[derive(Debug, Clone)]
pub struct Profile {
    bytes: [u8; PROFILE_LEN],
}

impl Profile {
    /// Wrap raw profile bytes.
    pub fn from_bytes(bytes: &[u8]) -> Result<Self> {
        if bytes.len() != PROFILE_LEN {
            return Err(Y65sError::BadInput(format!(
                "profile must be {PROFILE_LEN} bytes, got {}",
                bytes.len()
            )));
        }
        let mut raw = [0u8; PROFILE_LEN];
        raw.copy_from_slice(bytes);
        Ok(Self { bytes: raw })
    }

    /// Read the factory profile out of a flash dump.
    pub fn from_dump(dump: &[u8], live: bool) -> Result<Self> {
        let slice = if live {
            live_profile(dump)?
        } else {
            factory_profile(dump)?
        };
        Self::from_bytes(slice)
    }

    /// The raw bytes.
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    /// One known field.
    pub fn field(&self, field: &ProfileField) -> u8 {
        self.bytes[field.offset as usize]
    }

    /// All known fields with their current values.
    pub fn fields(&self) -> Vec<(ProfileField, u8)> {
        PROFILE_FIELDS.iter().map(|f| (*f, self.field(f))).collect()
    }

    /// Set the lighting effect index and/or mode.
    pub fn set_lighting(&mut self, effect: Option<u8>, mode: Option<u8>) {
        if let Some(e) = effect {
            self.bytes[LED_EFFECT_INDEX as usize] = e;
        }
        if let Some(m) = mode {
            self.bytes[LED_EFFECT_MODE as usize] = m;
        }
    }

    /// Set the volume level (0..=100 as the system reports it).
    pub fn set_volume(&mut self, level: u8) {
        self.bytes[VOLUME_LEVEL as usize] = level.min(100);
    }

    /// Re-stamp the "initialised" marker.
    pub fn stamp_marker(&mut self) {
        self.bytes[0x7E..0x80].copy_from_slice(&PROFILE_MARKER);
    }
}

/// The clock payload of the vendor app: three system-parameter bytes followed
/// by the time fields.
///
/// The layout was read out of the official `OemDrv.exe` (the app multiplies
/// the Windows master volume by 100.0 and sends the current time in the same
/// "system parameter" packet).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ClockPayload {
    /// The three leading system-parameter bytes (date / cpu / spare).
    pub head: [u8; 3],
    /// Year, low byte.
    pub year_lo: u8,
    /// Year, high byte.
    pub year_hi: u8,
    /// Month, 1..=12.
    pub month: u8,
    /// Day of month, 1..=31.
    pub day: u8,
    /// Hour, 0..=23.
    pub hour: u8,
    /// Minute, 0..=59.
    pub minute: u8,
    /// Second, 0..=59.
    pub second: u8,
    /// Weekday, 0 = Sunday.
    pub weekday: u8,
}

impl ClockPayload {
    /// Build the payload for a given date/time (weekday 0 = Sunday).
    pub fn new(
        year: u16,
        month: u8,
        day: u8,
        hour: u8,
        minute: u8,
        second: u8,
        weekday: u8,
    ) -> Self {
        Self {
            head: [0, 0, 0],
            year_lo: (year % 100) as u8,
            year_hi: (year / 100) as u8,
            month,
            day,
            hour,
            minute,
            second,
            weekday,
        }
    }

    /// The bytes as they go on the wire.
    pub fn to_bytes(self) -> [u8; 11] {
        [
            self.head[0],
            self.head[1],
            self.head[2],
            self.year_lo,
            self.year_hi,
            self.month,
            self.day,
            self.hour,
            self.minute,
            self.second,
            self.weekday,
        ]
    }
}

/// Where a clock packet may be delivered; the vendor app is not the only
/// possible carrier and the module has never told us which one it honours.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub struct ClockRoute {
    /// Record command to use.
    pub record: u8,
    /// Offset of the payload inside the record.
    pub at: usize,
    /// Sub-dispatch value, when the record uses one.
    pub sub: Option<u8>,
}

/// The routes we try when setting the clock, in the order we try them.
pub const CLOCK_ROUTES: &[ClockRoute] = &[
    ClockRoute {
        record: 0x04,
        at: DATA_OFF,
        sub: None,
    },
    ClockRoute {
        record: 0x04,
        at: 0,
        sub: None,
    },
    ClockRoute {
        record: 0x05,
        at: DATA_OFF,
        sub: Some(0),
    },
    ClockRoute {
        record: 0x05,
        at: DATA_OFF,
        sub: Some(1),
    },
    ClockRoute {
        record: 0x05,
        at: DATA_OFF,
        sub: Some(2),
    },
    ClockRoute {
        record: 0x03,
        at: DATA_OFF,
        sub: Some(1),
    },
    ClockRoute {
        record: 0x03,
        at: DATA_OFF,
        sub: Some(2),
    },
    ClockRoute {
        record: 0x03,
        at: DATA_OFF,
        sub: Some(3),
    },
    ClockRoute {
        record: 0x03,
        at: DATA_OFF,
        sub: Some(4),
    },
];

/// The timing the module needs for a screen transfer.  Without these delays
/// the module accepts the bytes and renders nothing.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub struct ScreenTiming {
    /// Delay after the `SetGIFParam` start record.
    pub after_start_ms: u64,
    /// Delay after every page.
    pub per_page_ms: u64,
    /// Delay before the end record.
    pub before_end_ms: u64,
    /// Delay after the end record.
    pub after_end_ms: u64,
}

impl Default for ScreenTiming {
    fn default() -> Self {
        Self {
            after_start_ms: 120,
            per_page_ms: 50,
            before_end_ms: 50,
            after_end_ms: 500,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn record_has_cmd_and_window() {
        let rec = build_record(0x04, &[1, 2, 3], DATA_OFF, None);
        assert_eq!(rec.len(), PAYLOAD);
        assert_eq!(rec[0], 0x04);
        assert_eq!(&rec[DATA_OFF..DATA_OFF + 3], &[1, 2, 3]);
        assert!(rec[DATA_OFF + 3..].iter().all(|b| *b == 0));
    }

    #[test]
    fn record_does_not_overflow() {
        let big = vec![0xAAu8; PAYLOAD];
        let rec = build_record(0x05, &big, DATA_OFF, None);
        assert_eq!(rec.len(), PAYLOAD);
    }

    #[test]
    fn sub_goes_to_the_right_byte() {
        let rec = build_record(0x05, &[], DATA_OFF, Some((3, 4)));
        assert_eq!(rec[4], 3);
        let rec = build_record(0x03, &[], DATA_OFF, Some((2, 1)));
        assert_eq!(rec[1], 2);
    }

    #[test]
    fn profile_from_dump_uses_the_right_offsets() {
        let mut dump = vec![0u8; LIVE_PROFILE_OFF + PROFILE_LEN];
        dump[LIVE_PROFILE_OFF] = 0x42;
        dump[FACTORY_PROFILE_OFF] = 0x17;
        let live = Profile::from_dump(&dump, true).unwrap();
        let factory = Profile::from_dump(&dump, false).unwrap();
        assert_eq!(live.bytes()[0], 0x42);
        assert_eq!(factory.bytes()[0], 0x17);
    }

    #[test]
    fn profile_setters_touch_the_right_bytes() {
        let mut p = Profile::from_bytes(&[0u8; PROFILE_LEN]).unwrap();
        p.set_lighting(Some(7), Some(2));
        p.set_volume(42);
        p.stamp_marker();
        assert_eq!(p.bytes()[LED_EFFECT_INDEX as usize], 7);
        assert_eq!(p.bytes()[LED_EFFECT_MODE as usize], 2);
        assert_eq!(p.bytes()[VOLUME_LEVEL as usize], 42);
        assert_eq!(&p.bytes()[0x7E..0x80], &PROFILE_MARKER);
    }

    #[test]
    fn profile_rejects_wrong_size() {
        assert!(Profile::from_bytes(&[0u8; 12]).is_err());
    }

    #[test]
    fn clock_payload_layout() {
        let p = ClockPayload::new(2026, 10, 21, 9, 7, 3, 2);
        assert_eq!(p.to_bytes(), [0, 0, 0, 26, 20, 10, 21, 9, 7, 3, 2]);
    }
}
