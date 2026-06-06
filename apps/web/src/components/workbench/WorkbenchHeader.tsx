"use client";

import { PageHeader } from "@/components/ui/page-header";
import { useLanguage } from "@/lib/i18n/LanguageProvider";

export function WorkbenchHeader() {
  const { t } = useLanguage();
  return <PageHeader title={t("workbench.title")} description={t("workbench.description")} />;
}

export function WorkbenchEmpty() {
  const { t } = useLanguage();
  return <p className="mt-8 text-sm text-muted-foreground">{t("workbench.empty")}</p>;
}
