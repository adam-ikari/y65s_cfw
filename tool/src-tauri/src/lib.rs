//! YD-Y65S 键盘工具（Tauri v2 应用层）。

pub mod commands;

use tracing_subscriber::EnvFilter;

/// Build and run the desktop app.
pub fn run() {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")))
        .init();

    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            commands::status,
            commands::list_collections,
            commands::read_profile,
            commands::write_profile,
            commands::factory_restore,
            commands::set_clock,
            commands::flash_read,
            commands::flash_write,
            commands::fix_volume_bar,
            commands::key_combos,
            commands::link_modes,
            commands::list_patches,
            commands::check_patches,
            commands::build_patched,
        ])
        .run(tauri::generate_context!())
        .expect("error while running the Y65S tool");
}
