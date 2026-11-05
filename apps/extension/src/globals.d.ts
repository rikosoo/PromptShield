/** Definido pelo build: true só no build de desenvolvimento/teste (config local, página de opções, site de teste). */
declare const __DEV__: boolean;

/** Definido pelo build --sideload: lê a configuração gravada pelo sensor (promptshield-config.json) e aceita API em http. */
declare const __SIDELOAD__: boolean;
