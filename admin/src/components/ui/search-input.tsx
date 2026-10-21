import * as React from "react";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface SearchInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange"> {
  value: string;
  onValueChange: (value: string) => void;
  label: string;
}

export function SearchInput({
  value,
  onValueChange,
  label,
  className,
  ...props
}: SearchInputProps) {
  return (
    <div className={cn("ui-search", className)}>
      <Search aria-hidden="true" />
      <input
        type="search"
        aria-label={label}
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
        {...props}
      />
      {value && (
        <button
          type="button"
          className="ui-search-clear"
          aria-label="Очистить поиск"
          onClick={() => onValueChange("")}
        >
          <X aria-hidden="true" />
        </button>
      )}
    </div>
  );
}
