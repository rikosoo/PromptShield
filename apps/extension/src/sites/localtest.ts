import { enterSubmits, firstMatch, type SiteModule } from "./types";

/** Só existe no build de teste: imita um campo de prompt em uma página local. Nunca vai para produção. */
export const localtest: SiteModule = {
  id: "localtest",
  app: "chatgpt_web",
  matches: (h) => h === "127.0.0.1" || h === "localhost",
  findInput: (doc) => firstMatch(doc, ["#prompt", "[data-prompt-input]"]),
  findSend: (doc) => firstMatch(doc, ["#send", "[data-send]"]),
  isSubmitKey: enterSubmits,
};
