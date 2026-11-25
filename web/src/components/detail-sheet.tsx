"use client";

import { X } from "lucide-react";
import { type ReactNode, useEffect, useRef } from "react";

/** The details of one item, in a sheet over the screen: from the right on a wide screen, from the
 * bottom on a phone. A native modal <dialog>, so focus stays inside it, Escape closes it and focus
 * goes back to what opened it. A click outside it closes it too. */
export function DetailSheet({
  open,
  label,
  onClose,
  children,
}: {
  open: boolean;
  label: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-label={label}
      className="sheet"
      onClose={onClose}
      onClick={(event) => {
        // The dialog itself is only hit outside its content: on the backdrop.
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="flex max-h-[88dvh] flex-col md:h-full md:max-h-none">
        <div className="flex justify-end px-3 pt-3">
          <button
            type="button"
            onClick={onClose}
            className="btn btn-ghost size-9 p-0"
            aria-label="Close the details"
          >
            <X className="size-5" aria-hidden />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-8 md:px-7">{open && children}</div>
      </div>
    </dialog>
  );
}
