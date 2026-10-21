//! `y65s` -- command line front end for the YD-Y65S toolchain.
//!
//! The command that matters for most people:
//!
//! ```text
//! y65s fix-volume
//! ```
//!
//! reads the keyboard's own flash, saves a backup next to you, applies the
//! two reviewed patches that stop the screen from drawing a volume bar that
//! does not match the system, writes the result back and verifies it byte
//! for byte.  Nothing else about the keyboard changes: the profile, the
//! lighting and the key map survive.

use std::path::PathBuf;
use std::process::ExitCode;

use y65s_core::error::Y65sError;
use y65s_core::flash;
use y65s_core::patch;

const USAGE: &str = "\
YD-Y65S 工具（音量条修复 / 固件备份 / 刷写）

用法:
  y65s fix-volume [--backup <路径>]   一键修复音量条（读出 → 备份 → 打补丁 → 写入 → 校验）
  y65s backup <路径>                  只读出整片 flash 并保存（不做任何写入）
  y65s flash <镜像>                   把镜像刷进键盘（写入前自动备份）
  y65s patch <dump> <输出> [--id ID]  给一个 dump 打补丁，生成新镜像（不碰设备）
  y65s patches                        列出所有补丁
  y65s info                           显示键盘连接状态

选项:
  --backup <路径>   备份文件放哪（默认当前目录，文件名带时间戳）
  --id <ID>         用哪个补丁（可重复；默认全部音量相关补丁）
";

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        print!("{USAGE}");
        return ExitCode::from(2);
    }
    let command = args[0].as_str();
    let rest = &args[1..];

    let result = match command {
        "fix-volume" => cmd_fix_volume(rest),
        "backup" => cmd_backup(rest),
        "flash" => cmd_flash(rest),
        "patch" => cmd_patch(rest),
        "patches" => cmd_patches(),
        "info" => cmd_info(),
        "-h" | "--help" | "help" => {
            print!("{USAGE}");
            return ExitCode::SUCCESS;
        }
        other => Err(Y65sError::BadInput(format!("未知命令：{other}\n\n{USAGE}"))),
    };

    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => {
            eprintln!("失败：{err}");
            if let Some(hint) = err.hint() {
                eprintln!("提示：{hint}");
            }
            ExitCode::FAILURE
        }
    }
}

/// `--backup <path>` and `--id <id>` extraction.
struct Opts {
    backup: Option<PathBuf>,
    ids: Vec<String>,
    positional: Vec<String>,
}

fn parse_opts(args: &[String]) -> Result<Opts, Y65sError> {
    let mut opts = Opts {
        backup: None,
        ids: Vec::new(),
        positional: Vec::new(),
    };
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--backup" => {
                let value = args
                    .get(i + 1)
                    .ok_or_else(|| Y65sError::BadInput("--backup 后面要跟一个路径".into()))?;
                opts.backup = Some(PathBuf::from(value));
                i += 2;
            }
            "--id" => {
                let value = args
                    .get(i + 1)
                    .ok_or_else(|| Y65sError::BadInput("--id 后面要跟一个补丁 id".into()))?;
                opts.ids.push(value.clone());
                i += 2;
            }
            other => {
                opts.positional.push(other.to_string());
                i += 1;
            }
        }
    }
    Ok(opts)
}

fn cmd_fix_volume(args: &[String]) -> Result<(), Y65sError> {
    let opts = parse_opts(args)?;
    println!("=== 一键修复音量条 ===");
    println!("（会先自动备份整片 flash，再写入；写入过程中不要拔线）");
    let report = flash::fix_volume_bar(opts.backup.as_deref())?;
    for step in &report.steps {
        println!("  {step}");
    }
    println!();
    if report.already_fixed {
        println!("这台键盘的固件里已经有修复了，没有写入任何东西。");
    } else {
        println!("已应用补丁：{}", report.applied.join(" + "));
    }
    println!("备份：{}", report.backup.as_deref().unwrap_or("(未保存)"));
    println!("备份 md5：{}", report.backup_md5);
    if !report.already_fixed {
        println!("写入后 md5：{}", report.image_md5);
    }
    println!(
        "校验：{}",
        if report.verified {
            "通过 ✓"
        } else {
            "未通过 ✗"
        }
    );
    Ok(())
}

fn cmd_backup(args: &[String]) -> Result<(), Y65sError> {
    let opts = parse_opts(args)?;
    let path = opts
        .positional
        .first()
        .map(PathBuf::from)
        .unwrap_or_else(flash::default_backup_path);
    let (data, digest) = flash::backup_to(&path)?;
    println!(
        "已备份 {} 字节到 {}（md5={digest}）",
        data.len(),
        path.display()
    );
    Ok(())
}

fn cmd_flash(args: &[String]) -> Result<(), Y65sError> {
    let opts = parse_opts(args)?;
    let path = opts
        .positional
        .first()
        .map(PathBuf::from)
        .ok_or_else(|| Y65sError::BadInput("要刷哪个镜像？用法：y65s flash <镜像>".into()))?;

    // Never write without a way back.
    let backup_path = path.with_extension("pre-flash-backup.bin");
    println!("=== 刷写 {} ===", path.display());
    println!("写入前先备份到 {}", backup_path.display());
    match flash::backup_to(&backup_path) {
        Ok((_, digest)) => println!("  备份完成，md5={digest}"),
        Err(err) => {
            eprintln!("备份失败，中止写入：{err}");
            return Err(err);
        }
    }
    for step in flash::flash_image(&path)? {
        println!("  {step}");
    }
    println!("完成。备份在 {}", backup_path.display());
    Ok(())
}

fn cmd_patch(args: &[String]) -> Result<(), Y65sError> {
    let opts = parse_opts(args)?;
    let dump =
        opts.positional.first().map(PathBuf::from).ok_or_else(|| {
            Y65sError::BadInput("用法：y65s patch <dump> <输出> [--id ID]".into())
        })?;
    let out =
        opts.positional.get(1).map(PathBuf::from).ok_or_else(|| {
            Y65sError::BadInput("用法：y65s patch <dump> <输出> [--id ID]".into())
        })?;
    let ids = if opts.ids.is_empty() {
        flash::VOLUME_FIX.iter().map(|s| s.to_string()).collect()
    } else {
        opts.ids.clone()
    };
    let (image, applied) = flash::build_patched(&dump, &out, &ids)?;
    println!(
        "已按 {} 生成 {}（{} 字节，md5={}）",
        applied.join(" + "),
        out.display(),
        image.len(),
        flash::md5_hex(&image)
    );
    Ok(())
}

fn cmd_patches() -> Result<(), Y65sError> {
    println!("可用补丁：");
    for p in patch::PATCHES {
        println!("  {}", p.id);
        println!("    地址 0x{:04X}，{} 字节", p.address, p.expect.len());
        println!("    {}", p.description.replace('\n', " "));
        println!();
    }
    Ok(())
}

fn cmd_info() -> Result<(), Y65sError> {
    let collections = y65s_core::hid::list_collections()?;
    if collections.is_empty() {
        println!("没有找到 YD-Y65S（258a:019d）。");
        return Ok(());
    }
    println!("找到 {} 个 HID 集合：", collections.len());
    for c in collections {
        println!(
            "  {:04x}:{:04x}  usage {:04x}:{:04x}  {}",
            c.vid,
            c.pid,
            c.usage_page,
            c.usage,
            c.product.as_deref().unwrap_or("")
        );
    }
    Ok(())
}
