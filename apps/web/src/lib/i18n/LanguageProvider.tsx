"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { DICTIONARY, type Language, type TranslationKey } from "./dictionary";

const STORAGE_KEY = "jepx.lang";

type LanguageContextValue = {
  lang: Language;
  setLang: (next: Language) => void;
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

function readInitialLang(): Language {
  if (typeof window === "undefined") return "en";
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (v === "en" || v === "ja") return v;
  } catch {
    /* localStorage unavailable — fall through */
  }
  return "en";
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Language>("en");

  // Read the persisted choice on first client mount.
  useEffect(() => {
    const initial = readInitialLang();
    if (initial !== "en") setLangState(initial);
    document.documentElement.lang = initial;
  }, []);

  const setLang = useCallback((next: Language) => {
    setLangState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
    document.documentElement.lang = next;
  }, []);

  const t = useCallback(
    (key: TranslationKey, vars?: Record<string, string | number>) => {
      const entry = DICTIONARY[key];
      let raw: string = entry ? entry[lang] : (key as string);
      if (!raw) raw = entry ? entry.en : (key as string);
      if (vars) {
        for (const [k, v] of Object.entries(vars)) {
          raw = raw.replace(`{${k}}`, String(v));
        }
      }
      return raw;
    },
    [lang],
  );

  const value = useMemo<LanguageContextValue>(
    () => ({ lang, setLang, t }),
    [lang, setLang, t],
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage(): LanguageContextValue {
  const ctx = useContext(LanguageContext);
  if (!ctx) {
    // Permissive fallback for components that mount outside the provider
    // (e.g. error pages). Returns English unchanged.
    return {
      lang: "en",
      setLang: () => {},
      t: (key, vars) => {
        const entry = DICTIONARY[key];
        let raw: string = entry ? entry.en : (key as string);
        if (vars) {
          for (const [k, v] of Object.entries(vars)) {
            raw = raw.replace(`{${k}}`, String(v));
          }
        }
        return raw;
      },
    };
  }
  return ctx;
}
