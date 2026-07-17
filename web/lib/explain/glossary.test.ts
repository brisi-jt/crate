import { describe, expect, it } from "vitest";
import { allGlossaryEntries, GLOSSARY, resolveExplain } from "./glossary";
import { REFERENCED_METRICS } from "./refs";

describe("glossary completeness", () => {
  it("resolves every referenced metric ref (no orphan references)", () => {
    const missing = REFERENCED_METRICS.filter((ref) => !(ref in GLOSSARY));
    expect(missing).toEqual([]);
  });

  it("has no glossary entry that nothing references (no orphan entries)", () => {
    const referenced = new Set(REFERENCED_METRICS);
    const orphans = Object.keys(GLOSSARY).filter((key) => !referenced.has(key));
    expect(orphans).toEqual([]);
  });

  it("has no duplicate keys in the referenced checklist", () => {
    const seen = new Set<string>();
    const dupes: string[] = [];
    for (const ref of REFERENCED_METRICS) {
      if (seen.has(ref)) dupes.push(ref);
      seen.add(ref);
    }
    expect(dupes).toEqual([]);
  });
});

describe("glossary entry shape (the three-part contract)", () => {
  it("every entry answers what / how / source with non-empty prose", () => {
    for (const [key, entry] of Object.entries(GLOSSARY)) {
      expect(entry.term, `${key}.term`).toBeTruthy();
      expect(entry.what, `${key}.what`).toBeTruthy();
      expect(entry.how, `${key}.how`).toBeTruthy();
      expect(entry.source, `${key}.source`).toBeTruthy();
    }
  });

  it("passes the stranger test — no ticket / phase / plan / file references", () => {
    // Prose is for a brand-new user; internal vocabulary must not leak.
    const banned =
      /\b(ENG-\d|SUM-\d|SKW-\d|phase\s*\d|X[1-5]\b|P[0-9]-\d|TODO|metric_ref|\.tsx?\b|\.py\b|snapshot(kind)?)/i;
    const offenders: string[] = [];
    for (const [key, entry] of Object.entries(GLOSSARY)) {
      for (const field of ["term", "what", "how", "source"] as const) {
        if (banned.test(entry[field])) {
          offenders.push(`${key}.${field}: ${entry[field]}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("does not SHOUT — prose is hushed, not all-caps banners", () => {
    // A term may be an acronym (ARI, UMAP); the what/how/source sentences
    // should read as prose, never as caps warnings.
    const offenders: string[] = [];
    for (const [key, entry] of Object.entries(GLOSSARY)) {
      for (const field of ["what", "how"] as const) {
        // 4+ consecutive uppercase letters = a shouted word.
        if (/[A-Z]{5,}/.test(entry[field])) {
          offenders.push(`${key}.${field}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe("resolveExplain", () => {
  it("returns the entry for a known ref", () => {
    const entry = resolveExplain("ari");
    expect(entry).not.toBeNull();
    expect(entry?.term).toBeTruthy();
  });

  it("returns null for an unknown ref rather than throwing", () => {
    expect(resolveExplain("no_such_metric_xyz")).toBeNull();
  });
});

describe("allGlossaryEntries", () => {
  it("returns one item per glossary entry, each carrying its ref key", () => {
    const all = allGlossaryEntries();
    expect(all.length).toBe(Object.keys(GLOSSARY).length);
    for (const item of all) {
      expect(item.ref).toBeTruthy();
      expect(item.entry.term).toBeTruthy();
    }
  });

  it("is sorted alphabetically by term for a browsable index", () => {
    const terms = allGlossaryEntries().map((e) => e.entry.term);
    const sorted = [...terms].sort((a, b) => a.localeCompare(b));
    expect(terms).toEqual(sorted);
  });
});
