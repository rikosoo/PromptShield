import { chatgpt } from "./chatgpt";
import { claude } from "./claude";
import { copilot } from "./copilot";
import { gemini } from "./gemini";
import { localtest } from "./localtest";
import type { SiteModule } from "./types";

export const SITES: SiteModule[] = __DEV__ ? [chatgpt, claude, gemini, copilot, localtest] : [chatgpt, claude, gemini, copilot];

export function siteFor(hostname: string): SiteModule | undefined {
  return SITES.find((s) => s.matches(hostname));
}
