import { useEffect, useState } from "react";
import {
  Clock,
  Cpu,
  Download,
  Factory,
  Keyboard,
  Lightbulb,
  RefreshCw,
  Terminal,
  Usb,
} from "lucide-react";
import * as api from "./api";
import type { ClockReport, Combo, DeviceInfo, LinkMode, ProfileView, Status } from "./api";

const TABS = [
  { id: "status", label: "状态", icon: Usb },
  { id: "light", label: "灯效", icon: Lightbulb },
  { id: "clock", label: "校时", icon: Clock },
  { id: "firmware", label: "固件", icon: Cpu },
  { id: "keys", label: "按键说明", icon: Keyboard },
] as const;

type TabId = (typeof TABS)[number]["id"];

/** A flash dump is the source of the profile and the target of a restore. */
const DEFAULT_DUMP = "firmware/backups/YD-Y65S_full_20261019.bin";

export default function App() {
  const [tab, setTab] = useState<TabId>("status");
  const [status, setStatus] = useState<Status | null>(null);
  const [collections, setCollections] = useState<DeviceInfo[]>([]);
  const [profile, setProfile] = useState<ProfileView | null>(null);
  const [clock, setClock] = useState<ClockReport | null>(null);
  const [combos, setCombos] = useState<Combo[]>([]);
  const [modes, setModes] = useState<LinkMode[]>([]);
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [dump, setDump] = useState(DEFAULT_DUMP);
  const [patches, setPatches] = useState<api.Patch[]>([]);
  const [patchState, setPatchState] = useState<Record<string, boolean>>({});
  const [fixSteps, setFixSteps] = useState<string[]>([]);

  const say = (line: string) =>
    setLog((prev) => [`${new Date().toLocaleTimeString()}  ${line}`, ...prev].slice(0, 200));

  const guard = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      const r = await fn();
      say(`${label}: ${JSON.stringify(r)}`);
      return r;
    } catch (e) {
      say(`${label} 失败: ${e}`);
      return null;
    } finally {
      setBusy(false);
    }
  };

  const refresh = async () => {
    const s = await api.status().catch(() => null);
    if (s) setStatus(s);
    const c = await api.listCollections().catch(() => []);
    setCollections(c);
  };

  useEffect(() => {
    refresh();
    api.keyCombos().then(setCombos).catch(() => {});
    api.linkModes().then(setModes).catch(() => {});
    api.listPatches().then(setPatches).catch(() => {});
  }, []);

  return (
    <div className="flex h-screen">
      <aside className="w-44 shrink-0 border-r border-white/10 bg-black/30 p-3">
        <div className="mb-4 px-2 text-sm font-semibold text-white/80">YD-Y65S 工具</div>
        <nav className="space-y-1">
          {TABS.map((t) => {
            const Icon = t.icon;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm ${
                  tab === t.id ? "bg-white/10 text-white" : "text-white/60 hover:bg-white/5"
                }`}
              >
                <Icon size={15} />
                {t.label}
              </button>
            );
          })}
        </nav>
        <div className="mt-6 px-2 text-[11px] leading-4 text-white/35">
          写操作只改模块与屏幕，
          <br />
          刷写固件会动键盘 flash，
          <br />
          请先备份。
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto p-6">
        <div className="mb-4 flex items-center gap-3">
          <h1 className="text-lg font-semibold">{TABS.find((t) => t.id === tab)?.label}</h1>
          <button
            onClick={refresh}
            className="flex items-center gap-1 rounded border border-white/15 px-2 py-1 text-xs text-white/70 hover:bg-white/5"
          >
            <RefreshCw size={12} /> 刷新
          </button>
          {busy && <span className="text-xs text-amber-300/80">执行中…</span>}
        </div>

        {tab === "status" && (
          <section className="space-y-4">
            <Card title="连接状态">
              <Row k="键盘" v={status?.connected ? "已连接" : "未连接"} />
              <Row k="后端" v={status?.backend ?? "-"} />
              {status?.note && <Row k="备注" v={status.note} />}
            </Card>
            <Card title="HID 集合（VID 258A / PID 019D）">
              {collections.length === 0 && <p className="text-white/40">没有看到任何集合</p>}
              {collections.map((c, i) => (
                <Row
                  key={i}
                  k={`${c.usage_page.toString(16)}:${c.usage.toString(16)}`}
                  v={c.product ?? "-"}
                />
              ))}
            </Card>
          </section>
        )}

        {tab === "light" && (
          <LightPanel
            dump={dump}
            setDump={setDump}
            profile={profile}
            setProfile={setProfile}
            guard={guard}
          />
        )}

        {tab === "clock" && (
          <section className="space-y-4">
            <Card title="把 PC 的时间写进屏幕模块">
              <p className="mb-3 text-xs leading-5 text-white/50">
                厂商的 OemDrv 会在打开键盘时每秒下发一次时间包（11 字节：
                3 字节系统参数 + 年/月/日/时/分/秒/星期）。我们用同一条通道。
              </p>
              <div className="flex flex-wrap gap-2">
                <Btn onClick={() => guard("校时", () => api.setClock(false))}>立即校时</Btn>
                <Btn
                  onClick={async () => {
                    const r = await guard("校时扫描", () => api.setClock(true));
                    if (r) setClock(r as ClockReport);
                  }}
                >
                  扫描全部通道（每条一个分钟数）
                </Btn>
              </div>
              {clock && (
                <table className="mt-4 w-full text-xs">
                  <thead className="text-white/40">
                    <tr>
                      <th className="text-left">记录</th>
                      <th className="text-left">偏移</th>
                      <th className="text-left">子命令</th>
                      <th className="text-left">时间</th>
                      <th className="text-left">应答</th>
                    </tr>
                  </thead>
                  <tbody>
                    {clock.attempts.map((a, i) => (
                      <tr key={i} className="border-t border-white/5">
                        <td className="py-1">0x{a.record.toString(16)}</td>
                        <td className="py-1">{a.at}</td>
                        <td className="py-1">{a.sub ?? "-"}</td>
                        <td className="py-1">{a.time}</td>
                        <td className="py-1 font-mono text-white/50">{a.answer || "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          </section>
        )}

        {tab === "firmware" && (
          <section className="space-y-4">
            <Card title="一键修复音量条">
              <p className="mb-3 text-xs leading-5 text-white/50">
                屏幕上那条音量条和系统音量对不上（甚至显示 100%）：厂商 app 把
                乘以 100 的系统音量原样转发给屏幕，8051 零限幅地照抄。
                这里的修复只改两处字节级补丁，主机侧的音量键照常工作，
                <b className="text-white/70">你的配置、灯效、键位都不动</b>。
              </p>
              <p className="mb-3 text-xs leading-5 text-white/40">
                过程：读出整片 flash → 存一份备份 → 打补丁 → 擦除写入 →
                读回逐字节校验。写入过程中不要拔线。
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <Btn
                  onClick={async () => {
                    const r = await guard("一键修复音量条", () => api.fixVolumeBar(null));
                    if (r) {
                      const rep = r as api.FixReport;
                      setFixSteps(rep.steps);
                      rep.steps.forEach((s) => say(s));
                      say(
                        rep.already_fixed
                          ? "固件里已经有修复，没有写入任何东西"
                          : `已应用 ${rep.applied.join(" + ")}，校验${rep.verified ? "通过" : "未通过"}`,
                      );
                    }
                  }}
                >
                  <Cpu size={12} /> 一键修复音量条
                </Btn>
                {fixSteps.length > 0 && (
                  <span className="text-xs text-emerald-300/80">{fixSteps[fixSteps.length - 1]}</span>
                )}
              </div>
              {fixSteps.length > 0 && (
                <pre className="mt-3 max-h-40 overflow-y-auto rounded bg-black/40 p-2 text-[11px] leading-4 text-white/60">
                  {fixSteps.join("\n")}
                </pre>
              )}
            </Card>
            <Card title="键盘 flash（ISP）">
              <label className="mb-3 block text-xs text-white/50">
                镜像路径
                <input
                  value={dump}
                  onChange={(e) => setDump(e.target.value)}
                  className="mt-1 w-full rounded border border-white/15 bg-black/30 px-2 py-1 text-white"
                />
              </label>
              <div className="flex flex-wrap gap-2">
                <Btn onClick={() => guard("备份 flash", () => api.flashRead("build/flash_backup.bin"))}>
                  <Download size={12} /> 备份整片 flash
                </Btn>
                <Btn
                  onClick={() =>
                    guard("刷写 flash", () => api.flashWrite(dump)).then(() => {
                      say("刷写后键盘会自动重启");
                    })
                  }
                >
                  刷回这个镜像
                </Btn>
              </div>
              <p className="mt-3 text-xs leading-5 text-white/40">
                刷写会先擦除应用区（0x0000–0xEFFF），bootloader 区（0xF000–0xFFFF）不动。
              </p>
            </Card>
            <Card title="自制固件 = 原厂固件 + 补丁">
              <p className="mb-3 text-xs leading-5 text-white/50">
                我们不改写整套固件，而是在原厂 dump 上做**可审计的字节级补丁**：
                每条补丁都带"期望的原字节"，对不上就拒绝打，避免把补丁打到错的地方。
              </p>
              {patches.length === 0 ? (
                <p className="text-xs text-white/35">
                  补丁表还是空的 —— 等音量上下限与"不发显示音量"两处地址确认后填进来。
                </p>
              ) : (
                <table className="w-full text-xs">
                  <thead className="text-white/40">
                    <tr>
                      <th className="text-left">补丁</th>
                      <th className="text-left">地址</th>
                      <th className="text-left">作用</th>
                      <th className="text-left">匹配</th>
                    </tr>
                  </thead>
                  <tbody>
                    {patches.map((p) => (
                      <tr key={p.id} className="border-t border-white/5 align-top">
                        <td className="py-1 font-mono">{p.id}</td>
                        <td className="py-1 font-mono">0x{p.address.toString(16)}</td>
                        <td className="py-1">{p.description}</td>
                        <td className="py-1">
                          {patchState[p.id] === undefined ? "?" : patchState[p.id] ? "✓" : "✗"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <Btn
                  onClick={async () => {
                    const r = await guard("检查补丁", () => api.checkPatches(dump));
                    if (r) {
                      const map: Record<string, boolean> = {};
                      (r as api.PatchReport[]).forEach((p) => (map[p.id] = p.applies));
                      setPatchState(map);
                    }
                  }}
                >
                  对着这个 dump 检查
                </Btn>
                <Btn
                  onClick={() =>
                    guard("生成补丁镜像", () =>
                      api.buildPatched(
                        dump,
                        "build/YD-Y65S_patched.bin",
                        Object.keys(patchState).filter((id) => patchState[id]),
                      ),
                    )
                  }
                >
                  生成补丁镜像
                </Btn>
              </div>
            </Card>
          </section>
        )}

        {tab === "keys" && (
          <section className="space-y-4">
            <Card title="按键组合（读自键盘自己的固件）">
              <table className="w-full text-xs">
                <tbody>
                  {combos.map((c, i) => (
                    <tr key={i} className="border-t border-white/5 align-top">
                      <td className="w-28 py-1 font-medium">{c.keys.join(" + ")}</td>
                      <td className="py-1">{c.effect}</td>
                      <td className="py-1 text-white/35">{c.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <Card title="连接方式">
              <table className="w-full text-xs">
                <tbody>
                  {modes.map((m) => (
                    <tr key={m.state} className="border-t border-white/5">
                      <td className="w-28 py-1">{m.name}</td>
                      <td className="py-1">{m.combo}</td>
                      <td className="py-1 text-white/35">0x{m.state.toString(16)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </section>
        )}
      </main>

      <aside className="w-72 shrink-0 border-l border-white/10 bg-black/30 p-3">
        <div className="mb-2 flex items-center gap-2 text-xs text-white/50">
          <Terminal size={12} /> 日志
        </div>
        <div className="space-y-1 overflow-y-auto text-[11px] leading-4 text-white/60">
          {log.map((l, i) => (
            <pre key={i} className="whitespace-pre-wrap break-all font-mono">
              {l}
            </pre>
          ))}
          {log.length === 0 && <p className="text-white/25">还没有操作</p>}
        </div>
      </aside>
    </div>
  );
}

function LightPanel(props: {
  dump: string;
  setDump: (v: string) => void;
  profile: ProfileView | null;
  setProfile: (p: ProfileView) => void;
  guard: (label: string, fn: () => Promise<unknown>) => Promise<unknown>;
}) {
  const { dump, setDump, profile, setProfile, guard } = props;
  const [effect, setEffect] = useState(11);
  const [mode, setMode] = useState(1);
  const [volume, setVolume] = useState(100);

  return (
    <section className="space-y-4">
      <Card title="profile（模块命令 0x52，128 字节）">
        <p className="mb-3 text-xs leading-5 text-white/50">
          灯效与音量都存在 profile 里：偏移 0x0A = 灯效序号，0x33 = 灯效模式，0x31 = 音量。
          修改后整块下发，模块即刻生效。
        </p>
        <label className="mb-3 block text-xs text-white/50">
          备份 / 镜像路径
          <input
            value={dump}
            onChange={(e) => setDump(e.target.value)}
            className="mt-1 w-full rounded border border-white/15 bg-black/30 px-2 py-1 text-white"
          />
        </label>
        <div className="flex flex-wrap items-end gap-3">
          <NumField label="灯效序号" value={effect} onChange={setEffect} />
          <NumField label="灯效模式" value={mode} onChange={setMode} />
          <NumField label="音量 0-100" value={volume} onChange={setVolume} />
          <Btn
            onClick={async () => {
              const r = await guard("写 profile", () =>
                api.writeProfile(dump, effect, mode, volume),
              );
              if (r) setProfile(r as ProfileView);
            }}
          >
            下发
          </Btn>
          <Btn
            onClick={async () => {
              const r = await guard("读 profile", () => api.readProfile(dump));
              if (r) setProfile(r as ProfileView);
            }}
          >
            读取
          </Btn>
        </div>
        {profile && (
          <table className="mt-4 w-full text-xs">
            <thead className="text-white/40">
              <tr>
                <th className="text-left">偏移</th>
                <th className="text-left">名称</th>
                <th className="text-left">当前</th>
                <th className="text-left">出厂</th>
              </tr>
            </thead>
            <tbody>
              {profile.fields.map((f) => (
                <tr key={f.offset} className="border-t border-white/5">
                  <td className="py-1 font-mono">0x{f.offset.toString(16)}</td>
                  <td className="py-1">{f.name}</td>
                  <td className="py-1">{f.value}</td>
                  <td className="py-1 text-white/35">{f.factory}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card title="恢复默认配置">
        <p className="mb-3 text-xs leading-5 text-white/50">
          把出厂 profile（flash 0x9983）整块写回模块，清掉我们改过的灯效与音量。
        </p>
        <Btn
          onClick={async () => {
            const r = await guard("恢复默认", () => api.factoryRestore(dump));
            if (r) setProfile(r as ProfileView);
          }}
        >
          <Factory size={12} /> 恢复默认配置
        </Btn>
      </Card>
    </section>
  );
}

function Card(props: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.02] p-4">
      <h2 className="mb-3 text-sm font-medium text-white/85">{props.title}</h2>
      {props.children}
    </div>
  );
}

function Row(props: { k: string; v: string }) {
  return (
    <div className="flex gap-3 border-t border-white/5 py-1 text-xs first:border-0">
      <span className="w-40 shrink-0 text-white/45">{props.k}</span>
      <span className="whitespace-pre-wrap break-all">{props.v}</span>
    </div>
  );
}

function NumField(props: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="text-xs text-white/50">
      {props.label}
      <input
        type="number"
        value={props.value}
        onChange={(e) => props.onChange(Number(e.target.value))}
        className="mt-1 w-24 rounded border border-white/15 bg-black/30 px-2 py-1 text-white"
      />
    </label>
  );
}

function Btn(props: {
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      onClick={props.onClick}
      className="flex items-center gap-1.5 rounded border border-white/15 bg-white/5 px-3 py-1.5 text-xs text-white/85 hover:bg-white/10"
    >
      {props.children}
    </button>
  );
}
