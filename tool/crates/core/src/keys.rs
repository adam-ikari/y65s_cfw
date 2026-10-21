//! The keyboard's key combinations.
//!
//! Everything here was read out of the keyboard's own firmware: the key map
//! table (flash 0xBC00..0xCC00) and the class 0x07 / 0x08 action handlers.
//! The entries are data, so the UI can show them without a second source.

use serde::{Deserialize, Serialize};

/// A key combination.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Combo {
    /// The keys to press, e.g. `["Fn", "Z"]`.
    pub keys: [&'static str; 2],
    /// What it does.
    pub effect: &'static str,
    /// Where the knowledge comes from.
    pub source: &'static str,
}

/// The wireless link modes the keyboard can be in.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct LinkMode {
    /// Short name.
    pub name: &'static str,
    /// The value the firmware stores in `xdata[0x0F29]`.
    pub state: u8,
    /// How to select it.
    pub combo: &'static str,
}

/// All link modes.
pub const LINK_MODES: &[LinkMode] = &[
    LinkMode {
        name: "USB 有线",
        state: 0x01,
        combo: "插上 USB 线即自动切到 USB",
    },
    LinkMode {
        name: "2.4G 接收器",
        state: 0x25,
        combo: "Fn + V",
    },
    LinkMode {
        name: "蓝牙 1",
        state: 0x35,
        combo: "Fn + Z",
    },
    LinkMode {
        name: "蓝牙 2",
        state: 0x45,
        combo: "Fn + X",
    },
    LinkMode {
        name: "蓝牙 3",
        state: 0x55,
        combo: "Fn + C",
    },
];

/// The combinations we know about.
pub const COMBOS: &[Combo] = &[
    Combo {
        keys: ["Fn", "V"],
        effect: "切到 2.4G 接收器模式",
        source: "class 0x07 子码 0x08 (状态 0x25)",
    },
    Combo {
        keys: ["Fn", "Z"],
        effect: "切到蓝牙 1",
        source: "class 0x07 子码 0x05 (状态 0x35)",
    },
    Combo {
        keys: ["Fn", "X"],
        effect: "切到蓝牙 2",
        source: "class 0x07 子码 0x06 (状态 0x45)",
    },
    Combo {
        keys: ["Fn", "C"],
        effect: "切到蓝牙 3",
        source: "class 0x07 子码 0x07 (状态 0x55)",
    },
    Combo {
        keys: ["Fn", "4"],
        effect: "按下时按住 右Shift + 右Win",
        source: "键位表 06:00:00:21 (chord 0xA0 + KC_4)",
    },
    Combo {
        keys: ["Fn", "O"],
        effect: "consumer 0x018A",
        source: "键位表 Fn 层第 4 行",
    },
    Combo {
        keys: ["Fn", "空格"],
        effect: "灯效：预设切换",
        source: "class 0x08 动作 0x00",
    },
    Combo {
        keys: ["Fn", "Delete"],
        effect: "灯效：亮度 +",
        source: "class 0x08 动作 0x01",
    },
    Combo {
        keys: ["Fn", "PageUp"],
        effect: "灯效：亮度 -",
        source: "class 0x08 动作 0x02",
    },
    Combo {
        keys: ["Fn", "PageDown"],
        effect: "灯效：切换预设",
        source: "class 0x08 动作 0x03",
    },
];

/// The media keys on the base layer (they work over every link mode).
pub const MEDIA_KEYS: &[&str] = &[
    "媒体播放/暂停",
    "上一曲",
    "下一曲",
    "静音",
    "音量减",
    "音量加",
    "计算器",
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn link_modes_cover_usb_2g_and_three_bt_slots() {
        assert_eq!(LINK_MODES.len(), 5);
        assert!(LINK_MODES.iter().any(|m| m.state == 0x01));
        assert!(LINK_MODES.iter().any(|m| m.state == 0x25));
        assert_eq!(
            LINK_MODES
                .iter()
                .filter(|m| (0x35..=0x55).contains(&m.state))
                .count(),
            3
        );
    }

    #[test]
    fn combos_are_unique() {
        let mut seen = std::collections::HashSet::new();
        for c in COMBOS {
            assert!(
                seen.insert(c.keys.join("+")),
                "duplicate combo {:?}",
                c.keys
            );
        }
    }
}
