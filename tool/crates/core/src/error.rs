//! Error type for the YD-Y65S toolchain.

/// Everything that can go wrong while talking to the keyboard.
#[derive(Debug, thiserror::Error)]
pub enum Y65sError {
    /// No HID device with the requested VID/PID/usage could be found.
    #[error("device not found: {0}")]
    DeviceNotFound(String),

    /// The device was found but could not be opened.
    #[error("cannot open device: {0}")]
    Open(String),

    /// A HID transfer failed.
    #[error("hid transfer failed: {0}")]
    Transfer(String),

    /// The device answered, but not with the frame we expected.
    #[error("unexpected answer frame: {0}")]
    BadAnswer(String),

    /// A file we depend on is missing or malformed.
    #[error("bad input: {0}")]
    BadInput(String),

    /// The ISP (flash) layer refused or failed.
    #[error("isp: {0}")]
    Isp(String),

    /// Anything else.
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
}

impl Y65sError {
    /// Short, user facing hint: what should the operator try next?
    pub fn hint(&self) -> Option<&'static str> {
        match self {
            Y65sError::DeviceNotFound(_) => Some(
                "接上键盘的 USB 线；若在 Linux 上提示权限不足，\
                 安装 udev 规则后重新插拔（见 tool/README.md）",
            ),
            Y65sError::Open(_) => {
                Some("设备可能正被别的程序占用（厂商驱动 / sinowisp / 另一个实例）")
            }
            Y65sError::Transfer(_) => Some("重试一次；仍失败则重新插拔 USB"),
            Y65sError::BadAnswer(_) => Some("重试一次；仍失败则重新插拔 USB"),
            Y65sError::BadInput(_) => None,
            Y65sError::Isp(_) => Some("确认键盘已重启并重新连接后再试"),
            Y65sError::Io(_) => None,
        }
    }

    /// The error plus its hint, as one message for the UI.
    pub fn full(&self) -> String {
        match self.hint() {
            Some(hint) => format!("{self}\n提示：{hint}"),
            None => self.to_string(),
        }
    }
}

/// Result alias used across the crate.
pub type Result<T> = std::result::Result<T, Y65sError>;
