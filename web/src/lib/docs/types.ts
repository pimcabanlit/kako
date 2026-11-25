// The documentation screen's pages, as data: each page is sections of blocks, written once and
// rendered both as the page and as Markdown ("Copy page as Markdown"). Text inside a block is a
// small Markdown subset (inline.ts): `code`, **bold** and [a link](/docs/meko#memory).

/** How far a part is built, said on its section. */
export type Status = "built" | "in-part" | "planned";

export type Block =
  | { kind: "p"; text: string }
  | { kind: "list"; items: string[] }
  /** "In the story": the part, as the Villanuevas met it ("In the story · Session 2, Sep 15"). */
  | { kind: "story"; when?: string; text: string }
  /** A note beside the text, such as what this machine runs ("On this laptop"). */
  | { kind: "note"; label: string; text: string }
  /** A part not built yet: what it will be, said plainly. */
  | { kind: "placeholder"; label?: string; text: string }
  /** The datapack drawn as a box of its parts, each with its status. */
  | { kind: "pack"; label: string; parts: { title: string; status: Status; text: string }[] }
  /** A flow left to right: each node a step, each arrow the verb between two steps. */
  | {
      kind: "flow";
      nodes: { title: string; text: string; tone: "meko" | "kako" | "person" | "shared" }[];
      arrows: string[];
    }
  | { kind: "table"; head: string[]; rows: string[][] }
  /** Steps in order, each with a name: a flow such as conversation, memory, learning, promotion. */
  | { kind: "steps"; items: { title: string; text: string }[] }
  /** A dated line of the household's story; a step not shown yet is drawn hollow. */
  | { kind: "timeline"; items: { when: string; title: string; text: string; planned?: boolean }[] }
  /** Where to see it in the app. */
  | { kind: "see"; links: { href: string; label: string }[] };

export type Section = {
  id: string;
  title: string;
  status?: Status;
  blocks: Block[];
  /** Sub-sections (h3), listed under their section in "On this page". */
  children?: Section[];
};

export type DocPage = {
  slug: string;
  title: string;
  /** The one line under the title. */
  lead: string;
  /** Paragraphs before the first section. */
  intro?: Block[];
  /** Whether the page says, live, how this machine reaches Meko. */
  live?: "meko";
  /** A link out, beside "Copy page as Markdown". */
  external?: { href: string; label: string };
  sections: Section[];
  /** Where to read next, at the foot of the page. */
  next?: { href: string; label: string; text: string }[];
};

/** The documentation's menu: groups of pages; a group may instead list one page's sections. */
export type NavGroup =
  | { title: string; kind: "pages"; slugs: string[] }
  | { title: string; kind: "sections"; slug: string };
