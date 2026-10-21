import { invoke } from "@tauri-apps/api/core";

/** One HID collection of the keyboard. */
export interface DeviceInfo {
  vid: number;
  pid: number;
  product: string | null;
  usage_page: number;
  usage: number;
}

/** Device state. */
export interface Status {
  connected: boolean;
  backend: string;
  collections: DeviceInfo[];
  note: string;
}

/** One known profile field. */
export interface FieldView {
  offset: number;
  name: string;
  value: number;
  factory: number;
}

/** The device profile. */
export interface ProfileView {
  bytes: number[];
  fields: FieldView[];
}

/** One clock delivery attempt. */
export interface ClockAttemptView {
  record: number;
  at: number;
  sub: number | null;
  time: string;
  answer: string;
}

/** The result of a clock delivery. */
export interface ClockReport {
  attempts: ClockAttemptView[];
}

/** A key combination. */
export interface Combo {
  keys: string[];
  effect: string;
  source: string;
}

/** A wireless link mode. */
export interface LinkMode {
  name: string;
  state: number;
  combo: string;
}

/** List the HID collections of the keyboard. */
export const listCollections = () => invoke<DeviceInfo[]>("list_collections");

/** Is the keyboard reachable? */
export const status = () => invoke<Status>("status");

/** Read the live profile out of a flash dump. */
export const readProfile = (dump: string) => invoke<ProfileView>("read_profile", { dump });

/** Change the lighting and/or the volume and push the profile. */
export const writeProfile = (
  dump: string,
  effect: number | null,
  mode: number | null,
  volume: number | null,
) => invoke<ProfileView>("write_profile", { dump, effect, mode, volume });

/** Write the factory profile back to the module. */
export const factoryRestore = (dump: string) => invoke<ProfileView>("factory_restore", { dump });

/** Push the PC clock into the module. */
export const setClock = (sweep: boolean) => invoke<ClockReport>("set_clock", { sweep });

/** Push a BMP onto the screen. */
export const pushScreen = (path: string) => invoke<number>("push_screen", { path });

/** Fill the screen with one colour. */
export const fillScreen = (r: number, g: number, b: number) =>
  invoke<number>("fill_screen", { r, g, b });

/** Read the whole flash of the keyboard. */
export const flashRead = (path: string) => invoke<string>("flash_read", { path });

/** Write a flash image back to the keyboard. */
export const flashWrite = (path: string) => invoke<string>("flash_write", { path });

/** The key combinations the keyboard understands. */
export const keyCombos = () => invoke<Combo[]>("key_combos");

/** The wireless link modes. */
export const linkModes = () => invoke<LinkMode[]>("link_modes");

/** One firmware patch. */
export interface Patch {
  id: string;
  description: string;
  address: number;
  expect: number[];
  replace: number[];
}

/** Whether a patch applies to an image. */
export interface PatchReport {
  id: string;
  applies: boolean;
}

/** The patches our custom firmware is made of. */
export const listPatches = () => invoke<Patch[]>("list_patches");

/** Check the patch set against a flash dump. */
export const checkPatches = (dump: string) => invoke<PatchReport[]>("check_patches", { dump });

/** Build a patched firmware image from a dump. */
export const buildPatched = (dump: string, out: string) =>
  invoke<string>("build_patched", { dump, out });
