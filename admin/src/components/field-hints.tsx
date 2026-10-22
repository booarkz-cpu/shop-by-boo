import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CircleHelp } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { type Lang, translate, useLang } from "../i18n";
type Control =
  | HTMLInputElement
  | HTMLTextAreaElement
  | HTMLSelectElement
  | HTMLButtonElement;
interface Field {
  control: Control;
  slot: HTMLSpanElement;
  label: string;
  message: string;
}
function sourceText(node: Node): string {
  return node instanceof Text
    ? ((node as Text & { __i18nSource?: string }).__i18nSource ??
        node.textContent ??
        "")
    : "";
}
function fieldLabel(control: Control): string {
  const label =
    control.closest("label") ||
    (control.id
      ? document.querySelector<HTMLLabelElement>(
          `label[for="${CSS.escape(control.id)}"]`,
        )
      : null);
  const direct = label
    ? Array.from(label.childNodes).map(sourceText).join(" ").trim()
    : "";
  const placeholder =
    control instanceof HTMLInputElement ||
    control instanceof HTMLTextAreaElement
      ? (control.dataset.i18nPlaceholder ?? control.placeholder)
      : "";
  const provided =
    control.dataset.generatedHintLabel === "true"
      ? ""
      : control.dataset.i18nAria || control.getAttribute("aria-label");
  return provided || direct || placeholder || control.name || "Параметр";
}
function describe(control: Control, label: string, lang: Lang): string {
  const explicit = control.getAttribute(
    lang === "en" ? "data-hint-en" : "data-hint",
  );
  if (explicit) return explicit;
  const name = label.toLowerCase(),
    field = translate(lang, label),
    pick = (ru: string, en: string) => (lang === "ru" ? ru : en);
  if (
    (control instanceof HTMLInputElement && control.type === "password") ||
    /парол|password/.test(name)
  )
    return pick(
      "Введите пароль учётной записи. Панель не записывает его в локальное хранилище.",
      "Enter the account password. The panel does not write it to local storage.",
    );
  if (/2fa|однораз|otp/.test(name))
    return pick(
      "Введите одноразовый код из приложения-аутентификатора, если двухфакторная защита включена.",
      "Enter a one-time code from your authenticator if two-factor protection is enabled.",
    );
  if (/email|почт/.test(name))
    return pick(
      control.closest(".auth-card")
        ? "Укажите рабочий email администратора. Он используется для входа и системных уведомлений."
        : "Укажите адрес электронной почты для этой записи. Проверьте адрес перед сохранением.",
      control.closest(".auth-card")
        ? "Enter the administrator email used for sign-in and system notifications."
        : "Enter the email address for this record. Check it before saving.",
    );
  if (
    /найти|поиск|search/.test(name) ||
    (control instanceof HTMLInputElement && control.type === "search")
  )
    return pick(
      "Введите часть названия или идентификатора, чтобы отфильтровать список.",
      "Enter part of a name or identifier to filter the list.",
    );
  if (/профиль remnawave|remnawave profile/.test(name))
    return pick(
      "Выберите профиль Remnawave, через который будет выдаваться VPN-доступ по этому тарифу.",
      "Choose the Remnawave profile used to provision VPN access for this plan.",
    );
  if (/цена|сумма|стоим|price|amount/.test(name))
    return pick(
      "Денежное значение в валюте магазина. Используйте точку для дробной части и проверьте сумму перед подтверждением.",
      "A monetary value in the shop currency. Use a decimal point and check the amount before confirming.",
    );
  if (/uuid/.test(name))
    return pick(
      "Идентификатор записи Remnawave. Скопируйте UUID целиком; имя пользователя не заменяет UUID.",
      "The Remnawave record identifier. Copy the complete UUID; a username does not replace it.",
    );
  if (control instanceof HTMLInputElement && control.type === "file")
    return pick(
      `Выберите файл для загрузки.${control.accept ? ` Допустимые форматы: ${control.accept}.` : ""} Сервер проверяет формат и размер файла.`,
      `Choose a file to upload.${control.accept ? ` Accepted formats: ${control.accept}.` : ""} The server checks its format and size.`,
    );
  if (control instanceof HTMLInputElement && control.type === "datetime-local")
    return pick(
      /utc/.test(name)
        ? "Укажите дату и время в UTC. Публикация начнётся или закончится в указанное время."
        : "Укажите дату и время для этого события.",
      /utc/.test(name)
        ? "Enter a UTC date and time. Publication starts or ends at this time."
        : "Enter the date and time for this event.",
    );
  if (
    control instanceof HTMLInputElement &&
    (control.type === "checkbox" || control.type === "radio")
  )
    return pick(
      `Включите или отключите параметр «${field}». Проверьте подтверждение операции в этой форме.`,
      `Enable or disable “${field}”. Check the confirmation shown by this form.`,
    );
  if (control instanceof HTMLInputElement && control.type === "number") {
    const range = [
      control.min
        ? pick(`минимум ${control.min}`, `minimum ${control.min}`)
        : "",
      control.max
        ? pick(`максимум ${control.max}`, `maximum ${control.max}`)
        : "",
    ]
      .filter(Boolean)
      .join(", ");
    return pick(
      `Введите числовое значение для поля «${field}».${range ? ` Допустимый диапазон: ${range}.` : ""}`,
      `Enter a number for “${field}”.${range ? ` Allowed range: ${range}.` : ""}`,
    );
  }
  if (
    control instanceof HTMLSelectElement ||
    control.getAttribute("role") === "combobox"
  )
    return pick(
      `Выберите вариант для поля «${field}». Используйте стрелки, Enter для выбора и Escape для закрытия.`,
      `Choose an option for “${field}”. Use arrow keys, Enter to select and Escape to close.`,
    );
  if (control instanceof HTMLTextAreaElement)
    return pick(
      `Введите текст для поля «${field}». Проверьте содержание перед сохранением.`,
      `Enter the text for “${field}”. Review it before saving.`,
    );
  return pick(
    `Значение поля «${field}». Заполните его и проверьте перед подтверждением формы.`,
    `The value of “${field}”. Enter it and review it before confirming the form.`,
  );
}
function FieldHelp({ field }: { field: Field }) {
  const { lang } = useLang(),
    [open, setOpen] = useState(false);
  useEffect(() => {
    const focus = () => {
        if (field.control.getAttribute("aria-expanded") !== "true")
          setOpen(true);
      },
      close = () => setOpen(false),
      key = (event: KeyboardEvent) => {
        if (event.key === "Escape") close();
      };
    field.control.addEventListener("focus", focus);
    field.control.addEventListener("blur", close);
    field.control.addEventListener("click", close);
    document.addEventListener("keydown", key);
    if (document.activeElement === field.control) focus();
    return () => {
      field.control.removeEventListener("focus", focus);
      field.control.removeEventListener("blur", close);
      field.control.removeEventListener("click", close);
      document.removeEventListener("keydown", key);
    };
  }, [field.control]);
  return (
    <Tooltip open={open} onOpenChange={setOpen}>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="field-help-trigger"
          aria-label={`${lang === "ru" ? "Подсказка" : "Help"}: ${translate(lang, field.label)}`}
          onClick={(event) => {
            event.preventDefault();
            setOpen(!open);
          }}
        >
          <CircleHelp aria-hidden="true" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom">{field.message}</TooltipContent>
    </Tooltip>
  );
}
export function FieldHints() {
  const { lang } = useLang(),
    registry = useRef(new Map<Control, Field>()),
    [fields, setFields] = useState<Field[]>([]);
  useEffect(() => {
    let frame = 0;
    const decorate = () => {
      frame = 0;
      for (const [control, field] of registry.current)
        if (!control.isConnected) {
          field.slot.remove();
          registry.current.delete(control);
        }
      document
        .querySelectorAll<Control>(
          'input:not([type="hidden"]),textarea,select:not([hidden]),button[role="combobox"]',
        )
        .forEach((control) => {
          if (
            control.getAttribute("aria-hidden") === "true" ||
            control.closest("[data-field-help-slot]") ||
            control.closest("[data-no-field-help]")
          )
            return;
          const label = fieldLabel(control),
            message = describe(control, label, lang);
          control.dataset.hintSource = label;
          control.dataset.hintReady = "true";
          if (control.getAttribute("aria-description") !== message)
            control.setAttribute("aria-description", message);
          if (
            !control.hasAttribute("aria-labelledby") &&
            (!control.hasAttribute("aria-label") ||
              control.dataset.generatedHintLabel === "true")
          ) {
            control.dataset.generatedHintLabel = "true";
            if (control.getAttribute("aria-label") !== translate(lang, label))
              control.setAttribute("aria-label", translate(lang, label));
          }
          if (!control.title || control.dataset.generatedHintTitle === "true") {
            control.dataset.generatedHintTitle = "true";
            control.title = message;
          }
          const parent = control.closest("label") || control.parentElement;
          if (!parent) return;
          if (parent instanceof HTMLLabelElement) {
            parent.classList.add("has-field-help");
            parent.dataset.tooltip = message;
          }
          let field = registry.current.get(control);
          if (!field) {
            const slot = document.createElement("span");
            slot.dataset.fieldHelpSlot = "true";
            slot.dataset.fieldHelpSlotId = crypto.randomUUID();
            slot.className = "field-help-slot";
            parent.appendChild(slot);
            field = { control, slot, label, message };
            registry.current.set(control, field);
          } else if (field.message !== message || field.label !== label) {
            field = { ...field, label, message };
            registry.current.set(control, field);
          }
        });
      const next = Array.from(registry.current.values());
      setFields((previous) =>
        previous.length === next.length &&
        previous.every((field, index) => field === next[index])
          ? previous
          : next,
      );
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(decorate);
    };
    decorate();
    const observer = new MutationObserver(schedule);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: [
        "data-hint",
        "data-hint-en",
        "aria-label",
        "placeholder",
        "name",
        "min",
        "max",
        "accept",
      ],
    });
    return () => {
      observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [lang]);
  useEffect(
    () => () => {
      for (const field of registry.current.values()) field.slot.remove();
      registry.current.clear();
    },
    [],
  );
  return (
    <>
      {fields.map((field) =>
        createPortal(
          <FieldHelp field={field} />,
          field.slot,
          field.slot.dataset.fieldHelpSlotId,
        ),
      )}
    </>
  );
}
