import * as React from "react";
import { ChevronRight, Languages, Moon, Sun } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { translate, useLang } from "../i18n";
interface Option {
  value: string;
  text: string;
  disabled: boolean;
}
interface SelectFieldProps extends Omit<
  React.SelectHTMLAttributes<HTMLSelectElement>,
  "multiple" | "size"
> {
  "data-hint"?: string;
  "data-hint-en"?: string;
}
function textOf(children: React.ReactNode): string {
  return React.Children.toArray(children)
    .map((child) =>
      typeof child === "string" || typeof child === "number"
        ? String(child)
        : React.isValidElement<{ children?: React.ReactNode }>(child)
          ? textOf(child.props.children)
          : "",
    )
    .join("");
}
function optionsOf(children: React.ReactNode): Option[] {
  return React.Children.toArray(children).flatMap((child) => {
    if (
      !React.isValidElement<React.OptionHTMLAttributes<HTMLOptionElement>>(
        child,
      )
    )
      return [];
    if (child.type === React.Fragment) return optionsOf(child.props.children);
    if (child.type !== "option")
      throw new Error("SelectField accepts option elements and fragments");
    const text = textOf(child.props.children);
    return [
      {
        value: String(child.props.value ?? text),
        text,
        disabled: !!child.props.disabled,
      },
    ];
  });
}
function OptionIcon({ value }: { value: string }) {
  if (value === "dark") return <Moon aria-hidden="true" />;
  if (value === "light") return <Sun aria-hidden="true" />;
  if (value === "ru" || value === "en") return <Languages aria-hidden="true" />;
  return <ChevronRight aria-hidden="true" />;
}
export function SelectField({
  children,
  className,
  value,
  defaultValue,
  disabled,
  id,
  "aria-label": ariaLabel,
  "data-hint": dataHint,
  "data-hint-en": dataHintEn,
  ...props
}: SelectFieldProps) {
  const { lang } = useLang(),
    native = React.useRef<HTMLSelectElement>(null),
    trigger = React.useRef<HTMLButtonElement>(null),
    generatedId = React.useId(),
    options = optionsOf(children);
  const [uncontrolled, setUncontrolled] = React.useState(
    String(
      defaultValue ?? options.find((option) => !option.disabled)?.value ?? "",
    ),
  );
  const selected = String(value ?? uncontrolled),
    [label, setLabel] = React.useState(ariaLabel ?? props.name ?? "");
  React.useLayoutEffect(() => {
    if (ariaLabel) {
      setLabel(ariaLabel);
      return;
    }
    const parent = trigger.current?.closest("label");
    const text = parent
      ? Array.from(parent.childNodes)
          .filter((node) => node instanceof Text)
          .map((node) => node.textContent ?? "")
          .join(" ")
          .trim()
      : "";
    setLabel(text || props.name || "Выберите значение");
  }, [ariaLabel, props.name, lang]);
  function change(next: string) {
    const control = native.current;
    if (!control || control.matches(":disabled")) return;
    const nextValue = next.slice(3);
    control.value = nextValue;
    if (value === undefined) setUncontrolled(nextValue);
    control.dispatchEvent(new Event("change", { bubbles: true }));
  }
  return (
    <span className="select-field">
      <select
        {...props}
        ref={native}
        data-native-select="true"
        aria-hidden="true"
        tabIndex={-1}
        id={id ? `${id}-native` : undefined}
        hidden
        value={selected}
        disabled={disabled}
        onInvalid={(event) => {
          event.preventDefault();
          trigger.current?.focus();
          props.onInvalid?.(event);
        }}
      >
        {children}
      </select>
      <Select
        value={`rw:${selected}`}
        onValueChange={change}
        disabled={disabled}
      >
        <SelectTrigger
          ref={trigger}
          id={id ?? generatedId}
          aria-label={translate(lang, label)}
          aria-required={props.required || undefined}
          data-hint={dataHint}
          data-hint-en={dataHintEn}
          className={cn(className)}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem
              key={option.value}
              value={`rw:${option.value}`}
              disabled={option.disabled}
            >
              <span className="select-option-label">
                <OptionIcon value={option.value} />
                {translate(lang, option.text)}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </span>
  );
}
