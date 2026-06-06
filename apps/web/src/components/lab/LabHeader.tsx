"use client";

import { PageHeader } from "@/components/ui/page-header";
import { useLanguage } from "@/lib/i18n/LanguageProvider";

export function LabHeader({ windowLabel }: { windowLabel: string | null }) {
  const { t } = useLanguage();
  const label = windowLabel ?? t("lab.emptyWindow");
  return (
    <PageHeader
      title={t("lab.title")}
      description={
        <>
          {t("lab.description.prefix")}{" "}
          <span className="text-muted-foreground">
            {t("lab.window")} {label}
          </span>
        </>
      }
    />
  );
}

export function LabEmpty() {
  const { t } = useLanguage();
  return <p className="mt-8 text-sm text-muted-foreground">{t("lab.empty")}</p>;
}
