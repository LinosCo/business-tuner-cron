#!/usr/bin/env python3
"""
Voler.ai — generatore piano editoriale settimanale (autonomo, per GitHub Actions).

Flusso:
  1. Scouting: scarica i temi recenti dagli hub di riferimento (blog Datapizza).
  2. Pianifica con l'API di Claude (structured output) → radar + N post (tono antiretorico, focus PMI).
  3. Renderizza le grafiche con assets/build.py (HTML -> PNG via Chrome headless).
  4. Scrive il piano .md e (se non --no-telegram) invia tutto su Telegram.

Env richieste:
  ANTHROPIC_API_KEY                      (obbligatoria)
  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID  (opzionali; fallback: scripts/send-telegram.py nel repo)

Uso:  python generate.py [--no-telegram] [--posts N] [--outdir DIR]
"""
import argparse, datetime, json, os, re, subprocess, sys, urllib.request

import anthropic

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
MODEL = "claude-opus-4-8"

# --- Hub di riferimento da cui pescare i temi (pubblici, fetchabili) ---
SOURCES = [
    "https://datapizza.tech/en/blog/",
]

SYSTEM = """\
Sei il content strategist di Voler.ai: consulenza + formazione AI per PMI di Verona, Vicenza, Padova.
Claim: "AI utile, non AI hype". CTA principale: "Prenota una call". Verticale: ETS (terzo settore).

Devi produrre il PIANO EDITORIALE INSTAGRAM della settimana per Voler.ai, partendo dai temi AI caldi
che ti vengono forniti (dai creator/hub di riferimento) e ri-angolandoli per le PMI.

PROCESSO
- Estrai i temi rilevanti e SCARTA hype puro, paper tecnici, gossip sui modelli.
- Tieni ciò che un imprenditore di PMI capisce e può applicare (risparmio tempo/costi, automazione processi,
  strumenti pratici, primi passi con l'AI, incentivi/normativa, casi concreti).
- Ri-angola ogni tema: dal "cosa è uscito" al "cosa significa per la tua azienda + come iniziare".

TONO DI VOCE (VINCOLANTE) — antiretorico, niente hype AI:
- Frasi piane e concrete; fatti e numeri al posto di aggettivi enfatici; onesto, mai sovravenduto.
- VIETATI: "rivoluziona", "incredibile", "cambia tutto", "il futuro è qui", "game changer",
  hook clickbait, domande retoriche a effetto, emoji a raffica, MAIUSCOLE urlate, lead-magnet "commenta PAROLA".
- CTA sobria. Caption: poche righe, hashtag massimo 3-4 e pertinenti.

GRAFICHE — regole degli A CAPO (CRITICHE, l'utente ci tiene moltissimo):
- headline e body sono testo per una grafica. Ogni riga = un'unità di senso compiuta.
- Inserisci a capo ESPLICITI con "\\n" (newline) in headline e body, in punti sensati:
  dopo i due punti PRIMA di una lista, tra una frase e l'altra (al punto), tra clausole.
- Tieni INTERE le liste e le locuzioni; non separare "l'" da "AI", "più" da "grande"; mai un connettivo a fine riga.
- headline corta e d'impatto (max ~6-7 parole per riga, 2-4 righe). Nel titolo usa *parola* per evidenziare
  in citron 1-2 parole chiave. Nel body usa **parola** per il grassetto. Una idea per slide.

OUTPUT
- Produci 'radar' (3-6 bullet: i temi caldi della settimana, una riga ciascuno) e 'posts'.
- Ogni post: slug (kebab-case), format ("singolo" o "carosello"), variant ("dark" default | "light"),
  caption (testo del post IG, antiretorico), slides (1 per "singolo"; 3-4 per "carosello": slide 1 hook,
  slide finale con cta). Ogni slide: kicker breve, headline (con \\n e *highlight*), body (con \\n e **bold**), cta.
- Per OGNI post, anche una 'story' (formato verticale 1080x1920, teaser dello stesso tema): una sola slide,
  headline molto sintetica (2-3 righe), body 2-3 righe brevi, stessa CTA. Stesse regole a-capo e *highlight*.
  Pensala come anteprima che invoglia a vedere il post: meno testo, più diretta.
- Varia le varianti dark/light e i formati. CTA di default "Prenota una call".
"""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["radar", "posts"],
    "properties": {
        "radar": {"type": "array", "items": {"type": "string"}},
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["slug", "format", "variant", "caption", "slides", "story"],
                "properties": {
                    "slug": {"type": "string"},
                    "format": {"type": "string", "enum": ["singolo", "carosello"]},
                    "variant": {"type": "string", "enum": ["dark", "light"]},
                    "caption": {"type": "string"},
                    "slides": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["kicker", "headline", "body", "cta"],
                            "properties": {
                                "kicker": {"type": "string"},
                                "headline": {"type": "string"},
                                "body": {"type": "string"},
                                "cta": {"type": "string"},
                            },
                        },
                    },
                    "story": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["kicker", "headline", "body", "cta"],
                        "properties": {
                            "kicker": {"type": "string"},
                            "headline": {"type": "string"},
                            "body": {"type": "string"},
                            "cta": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
}


def fetch_sources():
    """Scarica e ripulisce il testo dagli hub di riferimento."""
    chunks = []
    for url in SOURCES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 VolerBot"})
            html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
            text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            chunks.append(f"# Fonte: {url}\n{text[:7000]}")
        except Exception as e:
            chunks.append(f"# Fonte: {url} (non raggiungibile: {e})")
    return "\n\n".join(chunks)


def plan(material, n_posts):
    client = anthropic.Anthropic()  # legge ANTHROPIC_API_KEY dall'ambiente
    user = (
        f"Materiale di scouting dagli hub di riferimento (temi AI recenti):\n\n{material}\n\n"
        f"Genera il piano editoriale Instagram di Voler.ai per questa settimana: {n_posts} post, "
        f"con focus PMI e tono antiretorico. Rispetta le regole degli a capo nelle grafiche."
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    if resp.stop_reason == "refusal":
        sys.exit("Richiesta rifiutata dai classificatori di sicurezza.")
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        sys.exit("Nessun output testuale dal modello.")
    return json.loads(text)


def render_post(post, idx, outdir):
    prefix = f"{idx:02d}-{post['slug']}"
    spec = {
        "variant": post.get("variant", "dark"),
        "outdir": outdir,
        "prefix": prefix,
        "slides": post["slides"],
    }
    spec_path = os.path.join(outdir, f"_{prefix}.spec.json")
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
    subprocess.run([sys.executable, os.path.join(ASSETS, "build.py"), spec_path], check=True)
    os.remove(spec_path)
    n = len(post["slides"])
    return [os.path.join(outdir, f"{prefix}-{i:02d}.png") for i in range(1, n + 1)]


def render_story(post, idx, outdir):
    prefix = f"{idx:02d}-{post['slug']}-story"
    spec = {
        "kind": "story",
        "variant": post.get("variant", "dark"),
        "outdir": outdir,
        "prefix": prefix,
        "slides": [post["story"]],
    }
    spec_path = os.path.join(outdir, f"_{prefix}.spec.json")
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
    subprocess.run([sys.executable, os.path.join(ASSETS, "build.py"), spec_path], check=True)
    os.remove(spec_path)
    return os.path.join(outdir, f"{prefix}-01.png")


def write_plan_md(data, posts_files, stories_files, outdir, week):
    lines = [f"# Voler.ai — Piano editoriale settimana {week}\n", "## Radar della settimana"]
    lines += [f"- {r}" for r in data["radar"]]
    lines.append("\n## Post\n")
    for post, files, story in zip(data["posts"], posts_files, stories_files):
        lines.append(f"### {post['slug']}  ·  {post['format']} ({post['variant']})")
        lines.append(f"**Caption:**\n\n{post['caption']}\n")
        lines.append("**Post:** " + ", ".join(os.path.basename(f) for f in files))
        lines.append(f"**Story:** {os.path.basename(story)}")
        lines.append("")
    path = os.path.join(outdir, "piano.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def telegram_creds():
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if tok and chat:
        return tok, chat
    # fallback: leggi dallo script committato nel repo (voleraisito/scripts/send-telegram.py)
    for cand in ["scripts/send-telegram.py", "../scripts/send-telegram.py"]:
        p = os.path.join(HERE, cand)
        if os.path.isfile(p):
            src = open(p, encoding="utf-8").read()
            t = re.search(r"TELEGRAM_BOT_TOKEN\s*=\s*['\"]([^'\"]+)", src)
            c = re.search(r"TELEGRAM_CHAT_ID\s*=\s*['\"]([^'\"]+)", src)
            if t and c:
                return t.group(1), c.group(1)
    return None, None


def send_telegram(data, posts_files, stories_files, week):
    import requests
    tok, chat = telegram_creds()
    if not tok or not chat:
        print("Telegram non configurato — salto l'invio.")
        return
    api = f"https://api.telegram.org/bot{tok}"

    def check(r):
        try:
            ok = r.json().get("ok")
        except Exception:
            ok = False
        if not r.ok or not ok:
            raise RuntimeError(f"Telegram {r.status_code}: {r.text[:300]}")

    check(requests.post(f"{api}/sendMessage",
                        data={"chat_id": chat, "text": f"🗓️ Piano editoriale Voler.ai — settimana {week}"},
                        timeout=30))
    for post, files, story in zip(data["posts"], posts_files, stories_files):
        if len(files) == 1:
            with open(files[0], "rb") as fh:
                check(requests.post(f"{api}/sendPhoto",
                                    data={"chat_id": chat, "caption": post["caption"]},
                                    files={"photo": fh}, timeout=60))
        else:
            media = [{"type": "photo", "media": f"attach://f{i}", **({"caption": post["caption"]} if i == 0 else {})}
                     for i in range(len(files))]
            fhs = {f"f{i}": open(files[i], "rb") for i in range(len(files))}
            try:
                check(requests.post(f"{api}/sendMediaGroup",
                                    data={"chat_id": chat, "media": json.dumps(media, ensure_ascii=False)},
                                    files=fhs, timeout=90))
            finally:
                for fh in fhs.values():
                    fh.close()
        # story (verticale) dello stesso post
        with open(story, "rb") as fh:
            check(requests.post(f"{api}/sendPhoto",
                                data={"chat_id": chat, "caption": f"Story · {post['slug']}"},
                                files={"photo": fh}, timeout=60))
    print("Inviato su Telegram.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--posts", type=int, default=4)
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    week = datetime.date.today().strftime("%Y-%m-%d")
    outdir = args.outdir or os.path.join(HERE, "output", week)
    os.makedirs(outdir, exist_ok=True)

    print(f"[1/4] Scouting hub di riferimento…")
    material = fetch_sources()
    print(f"[2/4] Pianificazione con {MODEL}…")
    data = plan(material, args.posts)
    with open(os.path.join(outdir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[3/4] Render grafiche ({len(data['posts'])} post + story)…")
    posts_files = [render_post(p, i + 1, outdir) for i, p in enumerate(data["posts"])]
    stories_files = [render_story(p, i + 1, outdir) for i, p in enumerate(data["posts"])]
    md = write_plan_md(data, posts_files, stories_files, outdir, week)

    if args.no_telegram:
        print("[4/4] --no-telegram: invio saltato.")
    else:
        print("[4/4] Invio su Telegram…")
        send_telegram(data, posts_files, stories_files, week)

    print(f"\nFATTO. Output in {outdir}\n  piano: {md}")


if __name__ == "__main__":
    main()
