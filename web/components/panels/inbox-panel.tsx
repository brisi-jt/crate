"use client";

import { useEffect, useState } from "react";
import { Readout } from "@/components/panels/right-dock";
import { Separator } from "@/components/ui/separator";
import {
  useDigest,
  useDigests,
  useGenerateDigest,
  useMarkDigestRead,
} from "@/hooks/api/use-digests";
import type { DigestItem } from "@/lib/api/schemas";
import {
  deepLinkFor,
  groupBySection,
  SECTION_TITLES,
  weekLabel,
} from "@/lib/inbox/logic";
import { openListeningDeck } from "@/lib/store/deck";
import { useUiStore } from "@/lib/store/ui";

/**
 * The inbox: weekly digests as a reading list. Opening a digest stamps it
 * read (clearing the chrome marker); every item deep-links into the room —
 * deck on a playlist, playlist on the map, or the frontier explorer.
 */
export function InboxPanelContent() {
  const digests = useDigests();
  const generate = useGenerateDigest();
  const [openId, setOpenId] = useState<number | null>(null);

  if (openId !== null) {
    return <DigestView digestId={openId} onBack={() => setOpenId(null)} />;
  }

  return (
    <>
      <div className="flex items-end gap-xl">
        <Readout label="Digests" value={String(digests.data?.total ?? "—")} />
        <button
          type="button"
          disabled={generate.isPending}
          onClick={() =>
            generate.mutate(undefined, {
              onSuccess: (digest) => setOpenId(digest.id),
            })
          }
          className="display-caps ml-auto cursor-pointer rounded-sm bg-amber px-md py-2xs text-amber-ink text-micro transition-colors duration-150 hover:bg-amber-press disabled:cursor-default disabled:opacity-45"
        >
          {generate.isPending ? "Compiling…" : "Compile this week"}
        </button>
      </div>

      <Separator />

      {digests.isPending ? (
        <span className="micro-caps text-text-muted">READING THE LOG…</span>
      ) : digests.isError ? (
        <div className="flex flex-col items-start gap-xs">
          <span className="micro-caps text-danger">INBOX UNAVAILABLE</span>
          <button
            type="button"
            onClick={() => digests.refetch()}
            className="micro-caps cursor-pointer text-text-secondary underline hover:text-text-primary"
          >
            Retry
          </button>
        </div>
      ) : (digests.data?.items.length ?? 0) === 0 ? (
        <div className="flex flex-col gap-xs">
          <span className="micro-caps text-text-muted">NOTHING ON FILE</span>
          <p className="max-w-[44ch] text-sm text-text-secondary">
            A digest lands here every Monday morning — new suggestions, library
            movement, listening notes, frontier shifts. Compile one now to read
            this week so far.
          </p>
        </div>
      ) : (
        <div className="flex flex-col">
          {digests.data?.items.map((digest) => (
            <button
              key={digest.id}
              type="button"
              onClick={() => setOpenId(digest.id)}
              className="flex cursor-pointer items-center gap-sm border-border-subtle border-b px-2xs py-sm text-left last:border-b-0 hover:bg-surface-2"
            >
              {/* Unread cue: a small amber tick, cleared once opened. */}
              <span
                className={`inline-block size-[6px] rounded-full ${
                  digest.read_at === null ? "bg-amber" : "bg-surface-2"
                }`}
              />
              <span className="data-readout text-sm text-text-primary">
                {weekLabel(digest.week_start)}
              </span>
              <span className="data-readout ml-auto text-micro text-text-muted">
                {digest.item_count} ITEMS
              </span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}

function DigestView({
  digestId,
  onBack,
}: {
  digestId: number;
  onBack: () => void;
}) {
  const digest = useDigest(digestId);
  const markRead = useMarkDigestRead();

  // Opening the digest IS the read — stamp it once the content arrives.
  const isUnread = digest.data?.read_at === null;
  const { mutate: stampRead } = markRead;
  useEffect(() => {
    if (isUnread) stampRead(digestId);
  }, [isUnread, stampRead, digestId]);

  if (digest.isPending) {
    return <span className="micro-caps text-text-muted">OPENING…</span>;
  }
  if (digest.isError || !digest.data) {
    return (
      <div className="flex flex-col items-start gap-xs">
        <span className="micro-caps text-danger">DIGEST UNAVAILABLE</span>
        <button
          type="button"
          onClick={onBack}
          className="micro-caps cursor-pointer text-text-secondary underline hover:text-text-primary"
        >
          Back to the inbox
        </button>
      </div>
    );
  }

  const groups = groupBySection(digest.data.items);

  return (
    <>
      <div className="flex items-center gap-sm">
        <button
          type="button"
          onClick={onBack}
          className="micro-caps cursor-pointer text-text-muted hover:text-text-primary"
        >
          ← ALL DIGESTS
        </button>
        <span className="data-readout ml-auto text-micro text-text-muted">
          {weekLabel(digest.data.week_start)}
        </span>
      </div>

      <Separator />

      {groups.length === 0 && (
        <p className="max-w-[44ch] text-sm text-text-secondary">
          A quiet week — no new suggestions, no library movement, nothing on the
          frontier. The map holds steady.
        </p>
      )}

      {groups.map((group) => (
        <section key={group.section} className="flex flex-col gap-xs">
          <span className="micro-caps text-text-muted">
            {SECTION_TITLES[group.section]}
          </span>
          <div className="flex flex-col gap-2xs">
            {group.items.map((item) => (
              <DigestItemRow key={item.id} item={item} />
            ))}
          </div>
        </section>
      ))}
    </>
  );
}

const LINK_LABELS = {
  deck: "OPEN DECK",
  playlist: "SHOW PLAYLIST",
  frontier: "OPEN FRONTIER",
} as const;

function DigestItemRow({ item }: { item: DigestItem }) {
  const openPlaylist = useUiStore((s) => s.openPlaylist);
  const openFrontier = useUiStore((s) => s.openFrontier);
  const setMapMode = useUiStore((s) => s.setMapMode);
  const link = deepLinkFor(item);

  return (
    <div className="flex items-baseline gap-sm rounded-xs px-2xs py-2xs">
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-sm text-text-primary">{item.title}</span>
        {item.body && (
          <span className="text-micro text-text-secondary">{item.body}</span>
        )}
      </div>
      {link && (
        <button
          type="button"
          onClick={() => {
            if (link.kind === "deck") {
              openListeningDeck(link.playlistId);
            } else if (link.kind === "playlist") {
              setMapMode("playlists");
              openPlaylist(link.playlistId);
            } else {
              openFrontier();
            }
          }}
          className="micro-caps ml-auto shrink-0 cursor-pointer text-text-muted hover:text-text-primary"
        >
          {LINK_LABELS[link.kind]}
        </button>
      )}
    </div>
  );
}
