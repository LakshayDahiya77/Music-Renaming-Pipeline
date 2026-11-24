"""Metadata and Tag injection engine for batch directory updates.

Allows injecting:
- Actor name (placed first among actors, de-duplicated)
- Sitename / Studio (added into square bracket [Tags], de-duplicated)
- Director (added into square bracket [Tags], de-duplicated)
- Special tags (added into square bracket [Tags], de-duplicated)
- Special phrase (added into curly braces {Phrase}, de-duplicated)
"""

import re
from pathlib import Path
from typing import Any, Optional

def clean_token(val: str) -> str:
    """Strips extra whitespace, quotes, and punctuation."""
    return val.strip().strip("'\"")

def inject_metadata_into_filename(
    filename: str,
    actor: str = "",
    sitename: str = "",
    director: str = "",
    tag: str = "",
    special_phrase: str = "",
) -> str:
    """Injects metadata into a proposed filename according to the naming rules."""
    p = Path(filename)
    stem = p.stem
    ext = p.suffix

    # ----------------------------------------------------
    # 1. Special Phrase Injection {Phrase}
    # ----------------------------------------------------
    if special_phrase:
        new_phrases = [
            clean_token(x).strip("{}")
            for x in special_phrase.split(",")
            if clean_token(x).strip("{}")
        ]
        m_phrase = re.search(r"\{([^}]+)\}\s*$", stem)
        if m_phrase:
            existing_phrases = [x.strip() for x in m_phrase.group(1).split(",") if x.strip()]
            for ph in new_phrases:
                if not any(x.lower() == ph.lower() for x in existing_phrases):
                    existing_phrases.append(ph)
            stem = stem[: m_phrase.start()].rstrip() + " {" + ", ".join(existing_phrases) + "}"
        else:
            stem = stem + " {" + ", ".join(new_phrases) + "}"

    # ----------------------------------------------------
    # 2. Square Brackets [Tags, Director, Sitename]
    # ----------------------------------------------------
    bracket_items: list[tuple[str, str]] = []
    if tag:
        for t in tag.split(","):
            val = clean_token(t)
            if val:
                bracket_items.append(("tag", val))
    if director:
        for d in director.split(","):
            val = clean_token(d)
            if val:
                bracket_items.append(("director", val))
    if sitename:
        for s in sitename.split(","):
            val = clean_token(s)
            if val:
                bracket_items.append(("sitename", val))

    if bracket_items:
        # Separate {Phrase} at the end if present
        m_phrase = re.search(r"\s*\{[^}]+\}\s*$", stem)
        phrase_suffix = ""
        if m_phrase:
            phrase_suffix = " " + stem[m_phrase.start() :].strip()
            stem_core = stem[: m_phrase.start()].rstrip()
        else:
            stem_core = stem

        m_br = re.search(r"\[([^\]]+)\]\s*$", stem_core)
        if m_br:
            existing_tags = [x.strip() for x in m_br.group(1).split(",") if x.strip()]
            for kind, val in bracket_items:
                # De-duplicate case-insensitively
                if not any(x.lower() == val.lower() for x in existing_tags):
                    existing_tags.append(val)
            stem = stem_core[: m_br.start()].rstrip() + " [" + ", ".join(existing_tags) + "]" + phrase_suffix
        else:
            new_tags = [val for kind, val in bracket_items]
            stem = stem_core + " [" + ", ".join(new_tags) + "]" + phrase_suffix

    # ----------------------------------------------------
    # 3. Actor Injection (Placed first among actors, de-duplicated)
    # ----------------------------------------------------
    if actor:
        injected_actors = [
            clean_token(a)
            for a in re.split(r"\s*&\s*", actor)
            if clean_token(a)
        ]

        # Check for starting date: YYYY.MM.DD - or YYYY.MM - or YYYY -
        date_pattern = r"^(\d{4}(?:\.\d{2})?(?:\.\d{2})?)\s*-\s*"
        m_date = re.match(date_pattern, stem)
        date_prefix = ""
        rest = stem
        if m_date:
            date_prefix = stem[: m_date.end()]
            rest = stem[m_date.end() :]

        # Locate where actor section ends: ' - ', ' 🖤 ', ' [', or ' {'
        m_delim = re.search(r"(\s+-\s+|\s+🖤\s+|\s+\[|\s+\{)", rest)
        if m_delim:
            actor_part = rest[: m_delim.start()].strip()
            after_actor = rest[m_delim.start() :]
        else:
            actor_part = rest.strip()
            after_actor = ""

        existing_actors = [a.strip() for a in re.split(r"\s*&\s*", actor_part) if a.strip()]

        to_prepend = []
        for a_inj in injected_actors:
            # Check de-duplication case-insensitively, also comparing without parens
            inj_base = a_inj.split("(")[0].strip().lower()
            already_exists = False
            for ex in existing_actors:
                ex_base = ex.split("(")[0].strip().lower()
                if ex.lower() == a_inj.lower() or ex_base == inj_base:
                    already_exists = True
                    break
            if not already_exists:
                to_prepend.append(a_inj)

        if to_prepend:
            new_actors = to_prepend + existing_actors
            new_actor_part = " & ".join(new_actors)
            stem = f"{date_prefix}{new_actor_part}{after_actor}"

    # Clean any accidental double spaces
    stem = re.sub(r"  +", " ", stem).strip()
    return f"{stem}{ext}"

def inject_into_plan_items(
    items: list[Any],
    target_folder: Optional[str] = None,
    actor: str = "",
    sitename: str = "",
    director: str = "",
    tag: str = "",
    special_phrase: str = "",
) -> int:
    """Applies injection to all matching PlanItem objects in a folder."""
    modified_count = 0
    is_all = not target_folder or target_folder.strip().upper() in ("ALL", "[ALL DIRECTORIES / ENTIRE PLAN]")

    for item in items:
        # Match folder if not ALL
        if not is_all:
            item_folder = getattr(item, "folder", "").strip()
            tgt = target_folder.strip()
            if item_folder != tgt and not item.old_path.startswith(tgt):
                continue

        old_proposed = item.proposed_name
        new_proposed = inject_metadata_into_filename(
            old_proposed,
            actor=actor,
            sitename=sitename,
            director=director,
            tag=tag,
            special_phrase=special_phrase,
        )

        if new_proposed != old_proposed:
            item.proposed_name = new_proposed
            item.is_modified = True
            modified_count += 1

    return modified_count

if __name__ == "__main__":
    import sys
    test_title = "2021.05.14 - Actor B - Scene Title [Anal].mp4"
    res = inject_metadata_into_filename(test_title, actor="Actor A", sitename="EvilAngel.com", special_phrase="Her Only Scene")
    print("Sample Run:")
    print("Before:", test_title)
    print("After: ", res)
