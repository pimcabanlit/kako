import Image from "next/image";

/** Kako's mark: the three rising bars, emerald, gold and orange, with the swoosh beneath them. A
 * picture beside the word "kako" or inside a labelled button, so it says nothing on its own. */
export function BrandMark({ size = 24, className = "" }: { size?: number; className?: string }) {
  return (
    <Image
      src="/kako-mark.png"
      alt=""
      width={size}
      height={size}
      className={`shrink-0 select-none ${className}`}
      draggable={false}
    />
  );
}

/** The mark, then the wordmark: the sidebar's header and a phone's top bar. */
export function Brand({ size = "md" }: { size?: "sm" | "md" }) {
  return (
    <span className="inline-flex items-center gap-2">
      <BrandMark size={size === "md" ? 26 : 22} />
      <span className={`wordmark ${size === "md" ? "text-[22px]" : "text-lg"}`}>kako</span>
    </span>
  );
}
