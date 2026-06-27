#!/usr/bin/env python3
"""
Genera le grafiche dei post Voler.ai (stile sito) da una spec JSON.
Uso:  python3 build.py spec.json
Ogni slide -> un PNG branded. Variante 'dark' (ink) o 'light' (cloud).

Formato spec.json:
{
  "variant": "dark",                 # "dark" | "light"  (default dark)
  "size": "1080x1350",               # default 1080x1350 (portrait IG)
  "outdir": "~/Downloads/voler-post", # cartella output (creata se assente)
  "prefix": "slide",                 # prefisso file (default "slide")
  "slides": [
    {
      "kicker": "AI per le PMI",
      "headline": "Con l'AI non serve un grande *budget* per partire",
      "body": "Uno studente l'ha fatto con **20€**. La tua PMI può iniziare oggi.",
      "cta": "Prenota una call"
      # "index": "1/3"   # opzionale: se assente e piu' slide -> auto "i/N"
    }
  ]
}
Markup nei testi:  *parola* -> evidenziata (citron) nel titolo ;  **parola** -> grassetto nel body.
Per niente CTA/kicker/index, metti stringa vuota "".
"""
import json, os, re, sys, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

def _lines(s):
    return (s or "").replace("\\n", "\n").split("\n")

def fmt_headline(s):
    # ogni riga (\n) = un blocco che NON va a capo da solo; *parola* = citron
    out = []
    for ln in _lines(s):
        ln = re.sub(r"\*(.+?)\*", r'<span class="hl">\1</span>', ln)
        out.append('<span class="hline">' + ln + '</span>')
    return "".join(out)

def fmt_body(s):
    if not s: return ""
    out = []
    for ln in _lines(s):
        ln = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", ln)
        out.append('<span class="bline">' + ln + '</span>')
    return "".join(out)

def main():
    if len(sys.argv) < 2:
        sys.exit("uso: python3 build.py spec.json")
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    variant = spec.get("variant", "dark")
    size = spec.get("size", "1080x1350")
    prefix = spec.get("prefix", "slide")
    outdir = os.path.expanduser(spec.get("outdir", "~/Downloads/voler-post"))
    os.makedirs(outdir, exist_ok=True)
    tpl_path = os.path.join(HERE, f"template-{variant}.html")
    template = open(tpl_path, encoding="utf-8").read()
    slides = spec["slides"]; n = len(slides)
    render = os.path.join(HERE, "render.sh")
    outputs = []
    for i, sl in enumerate(slides, 1):
        idx = sl.get("index")
        if idx is None:
            idx = f"{i}/{n}" if n > 1 else ""
        cta = sl.get("cta", "")
        cta_block = f'<span class="cta">{cta}</span>' if cta.strip() else '<span></span>'
        html = (template
                .replace("{{INDEX}}", idx)
                .replace("{{KICKER}}", sl.get("kicker", ""))
                .replace("{{HEADLINE}}", fmt_headline(sl.get("headline", "")))
                .replace("{{BODY}}", fmt_body(sl.get("body", "")))
                .replace("{{CTA_BLOCK}}", cta_block)
                .replace("{{CTA}}", cta))
        # l'HTML temporaneo va nella cartella assets cosi' logo e font relativi si caricano
        tmp = os.path.join(HERE, f"_build_{i}.html")
        open(tmp, "w", encoding="utf-8").write(html)
        out = os.path.join(outdir, f"{prefix}-{i:02d}.png")
        subprocess.run(["bash", render, tmp, out, size], check=True)
        os.remove(tmp)
        outputs.append(out)
        print(f"  slide {i}/{n} -> {out}")
    print(f"FATTO: {n} PNG in {outdir}")

if __name__ == "__main__":
    main()
