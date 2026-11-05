"use client";
import { useEffect, useState } from "react";
import { api } from "./api";
import type { TaxonomyItem } from "./types";

let cache: Promise<TaxonomyItem[]> | null = null;

/** As 30 categorias vêm da API (packages/taxonomy); nada de lista fixa no console. */
export function useTaxonomy() {
  const [items, setItems] = useState<TaxonomyItem[]>([]);
  useEffect(() => {
    cache ??= api<TaxonomyItem[]>("v1/taxonomy");
    cache.then(setItems, () => { cache = null; });
  }, []);
  const name = (id: string) => items.find((c) => c.id === id)?.nome ?? id.replace(/_/g, " ");
  const groups = [...new Set(items.map((c) => c.grupo))].map((g) => ({ group: g, items: items.filter((c) => c.grupo === g) }));
  return { items, name, groups };
}
