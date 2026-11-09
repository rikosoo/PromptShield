/** Política de senha do console (a mesma da API: quem decide é a API; aqui só mostramos o que falta). 8+ caracteres, minúscula, maiúscula, número e caractere especial. */
export interface Rule { id: string; label: string; ok: boolean }

export function passwordRules(pw: string): Rule[] {
  return [
    { id: "len", label: "Pelo menos 8 caracteres", ok: [...pw].length >= 8 },
    { id: "lower", label: "Uma letra minúscula", ok: /\p{Ll}/u.test(pw) },
    { id: "upper", label: "Uma letra maiúscula", ok: /\p{Lu}/u.test(pw) },
    { id: "digit", label: "Um número", ok: /\p{Nd}/u.test(pw) },
    { id: "special", label: "Um caractere especial (como ! @ # $ %)", ok: /[^\p{L}\p{N}\s]/u.test(pw) },
  ];
}

export const passwordOk = (pw: string) => pw.length <= 128 && passwordRules(pw).every((r) => r.ok);
