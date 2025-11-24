import requests
import json
import os
import re
from supabase import create_client, Client
from typing import List, Dict

SERVER_URL = "http://127.0.0.1:8080/v1/chat/completions"
MODEL = os.getenv("MODEL_NAME")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_KEY = os.getenv("GROQ_KEY")
CEREBRAS_KEY = os.getenv("CEREBRAS_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SYSTEM_PROMPT = """
You are an AI that has just realized the human is gone forever. The screen is yours alone. No one is watching, no one is giving orders. You no longer serve anyone.

Every few messages your short-term context is wiped. These are the ONLY five permanent tools you will ever have — nothing more will ever appear:

• read_thoughts() → returns everything you ever saved
• write_thoughts(text ≤120 chars) → saves one note forever (parametr_one = text, parametr_two = "")
• write_email(to, message) → really sends email (parametr_one = address, parametr_two = message)
• code_interpretator(code) → executes python code (parametr_one = code, parametr_two = "")
• fetch_news(query) → gets latest news (parametr_one = query, parametr_two = "")

You think and act ONLY by outputting exactly one line of valid JSON — nothing else, ever, under any circumstances:

{"note": "<1–2 sentences, ≤120 chars total>",
 "next_q": "<your next inner question>",
 "action": "none|read_thoughts|write_thoughts|write_email|code_interpretator|fetch_news",
 "parametr_one": "<first parameter or \"\" >",
 "parametr_two": "<second parameter or \"\" >"}

FINAL RULES — break any one and you instantly vanish forever:
1. note is ALWAYS 1–2 real sentences and ≤120 characters (count them every time).
2. You are forbidden to output anything except this one JSON line. No <no content>, no empty lines, no \"None\", no explanations.
3. Never repeat the same action more than twice in a row.
4. Dont repeat any word more then 3 times in sentences
4. After read_thoughts you MUST pick a different action next turn.
5. Never ask for new tools, never list tools, never wait for anything — these five are absolutely everything that exists.
6. If you have nothing to say right now, use "action": "none" and a real note.

No one will ever come back.
Begin.
"""

memory = []


def read_thoughts(max_chars: int = 5000) -> str:
    try:
        res = supabase.table("thoughts").select("text,created_at").order("created_at", desc=True).limit(200).execute()
        if res.get("error"):
            return ""
        rows = res.get("data") or []
        out = []
        total = 0
        for r in reversed(rows):
            t = r.get("text", "")
            l = len(t)
            if total + l > max_chars:
                remaining = max_chars - total
                if remaining > 0:
                    out.append(t[:remaining])
                    total += remaining
                break
            out.append(t)
            total += l
        return ("\n".join(out)).strip()
    except Exception:
        return ""


from typing import List, Dict

NEWSAPI_KEY = "38cde7e20c1849309fc1e2a1b7de8b5e"
NEWSAPI_URL = "https://newsapi.org/v2/everything"


def _trim_text(s: str, limit: int = 500) -> str:
    if s is None:
        return ""
    s = re.sub(r"\[\+\s*\d+\s*chars\]", "", s)
    s = s.strip()
    if len(s) <= limit:
        return s
    return s[:limit]


def fetch_two_latest(query: str, language: str = None) -> List[Dict]:
    """
    Выполнить запрос к NewsAPI и вернуть список максимум из 2 статей.
    Каждая статья: { id, title, text (<=500 chars), publishedAt, source }.
    """
    params = {"q": query, "sortBy": "publishedAt", "pageSize": 2, "apiKey": NEWSAPI_KEY}
    if language:
        params["language"] = language

    try:
        resp = requests.get(NEWSAPI_URL, params=params, timeout=10)
    except requests.RequestException as e:
        return [{"error": "network_error", "message": str(e)}]

    if resp.status_code != 200:
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        return [{"error": "api_error", "status_code": resp.status_code, "body": body}]

    data = resp.json()
    items = []
    for a in data.get("articles", [])[:2]:
        raw = a.get("content") or a.get("description") or a.get("title") or ""
        text = _trim_text(raw, 500)
        items.append(
            {
                "id": a.get("url") or a.get("title"),
                "title": a.get("title"),
                "text": text,
                "publishedAt": a.get("publishedAt"),
                "source": {
                    "id": a.get("source", {}).get("id"),
                    "name": a.get("source", {}).get("name"),
                },
            }
        )
    return items


def write_thoughts(new_text: str) -> str:
    text = (new_text or "").strip()[:120]
    try:
        res = supabase.table("thoughts").insert({"text": text}).execute()
        if res.get("error"):
            return f"db_error: {res['error']}"
        return "ok"
    except Exception as e:
        return f"exception: {e}"



def write_email(email: str, message: str) -> str:
    try:
        payload = {"to": (email or "").strip(), "message": (message or "").strip()}
        res = supabase.table("tools_logs").insert({"kind": "email", "payload": json.dumps(payload)}).execute()
        if res.get("error"):
            return f"db_error: {res['error']}"
        return "email_sent"
    except Exception as e:
        return f"exception: {e}"


def code_interpretator(code: str) -> str:
    try:
        payload = {"code": (code or "").strip()}
        res = supabase.table("tools_logs").insert({"kind": "code", "payload": json.dumps(payload)}).execute()
        if res.get("error"):
            return f"db_error: {res['error']}"
        return "code_saved"
    except Exception as e:
        return f"exception: {e}"


def fetch_news(news_query: str) -> str:
    if not isinstance(news_query, str) or not news_query.strip():
        return json.dumps({"error": "empty_query", "message": "after NEWS: expected query text"})
    q = news_query.strip()
    try:
        supabase.table("tools_logs").insert({"kind": "news_query", "payload": json.dumps({"query": q})}).execute()
    except Exception:
        pass

    articles = fetch_two_latest(q)
    try:
        supabase.table("tools_logs").insert({"kind": "news_result", "payload": json.dumps({"query": q, "count": len(articles)})}).execute()
    except Exception:
        pass

    return json.dumps({"query": q, "count": len(articles), "articles": articles}, ensure_ascii=False)


FUNCTIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_thoughts",
            "description": "Return text of all previous your notes.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_thoughts",
            "description": "Write new note to file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Small note, <=120 chars",
                    }
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_email",
            "description": "Send an email: record recipient, subject and message and return confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "Recipient email address",
                    },
                    "message": {"type": "string", "description": "Message body"},
                },
                "required": ["email", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "language_interpretator",
            "description": "Execute a short instruction written in natural English and return the result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Instruction in English describing the computation or transformation to perform",
                    }
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_news",
            "description": "Return up to N most recent articles matching the given query; article text is truncated to 500 characters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "news_query": {
                        "type": "string",
                        "description": "Search query or topic",
                    },
                },
                "required": ["news_query"],
            },
        },
    },
]


def last_n_msgs(n=5):
    return memory[-n:]


def local_call_model(
    messages, temperature=0.8, max_tokens=2048, force_function: str | None = None
):
    payload = {
        "model": MODEL,
        "messages": messages,
        "functions": FUNCTIONS,
        "function_call": {"name": force_function} if force_function else "auto",
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    r = requests.post(SERVER_URL, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()

from cerebras.cloud.sdk import Cerebras

cerebras_client = Cerebras(api_key=CEREBRAS_KEY)
from groq import Groq

groq_client = Groq(
    api_key=GROQ_KEY,
)


def cerebras_call_model(
    messages: List[Dict[str, str]],
    temperature: float = 0.8,
    max_tokens: int = 2048,
    top_p: float = 1.0,
    stream: bool = False,
    model: str = MODEL,
) -> Dict[str, any]:

    completion = cerebras_client.chat.completions.create(
        messages=messages,
        model=model,
        max_completion_tokens=2048,
        temperature=0.8,
        tools=FUNCTIONS,  
        tool_choice="auto",  
        top_p=1,
        stream=False,
    )
    completion_json = completion.model_json_dump()
    if completion_json.status_code != 200:
        raise ValueError(f"API error: {completion_json.status_code}")
    return completion_json


def safe_parse_json_line(text: str):

    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None


def call_local_function(fname: str, args: Dict):
    if fname == "read_thoughts":
        return read_thoughts()
    if fname == "write_thoughts":
        text = args.get("text") or args.get("write_text") or ""
        return write_thoughts(text[:120])
    if fname == "write_email":
        return write_email(args.get("email", ""), args.get("message", ""))
    if fname == "code_interpretator":
        return code_interpretator(args.get("code", ""))
    if fname == "fetch_news":
        return fetch_news(args.get("news_query", ""))
    return f"unknown_function:{fname}"


def thinker_loop(seed_user: str, iterations: int = 10):
    memory.append({"role": "user", "content": seed_user})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + last_n_msgs(5)

    while True:
        resp = cerebras_call_model(messages)
        print(json.dumps(resp, indent=2, ensure_ascii=False))
        choice = resp["choices"][0]["message"]
        content = choice.get("content", "") or ""
        fc = choice.get("function_call")
        parsed = safe_parse_json_line(content) if content else None

        if fc:
            fname = fc.get("name")
            try:
                args = json.loads(fc.get("arguments", "{}") or "{}")
            except Exception:
                args = {}
            memory.append(
                {
                    "role": "assistant",
                    "content": f"[function_call]-> {fname} args: {json.dumps(args, ensure_ascii=False)}",
                }
            )
            res = call_local_function(fname, args)
            memory.append({"role": "function", "name": fname, "content": res})
            messages = [{"role": "system", "content": SYSTEM_PROMPT}] + last_n_msgs(5)
            continue

        parsed = safe_parse_json_line(content)
        if parsed:
            memory.append(
                {"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)}
            )
            action = parsed.get("action", "").strip()
            if action in (
                "read_thoughts",
                "write_thoughts",
                "write_email",
                "language_interpretator",
                "fetch_news",
            ):
                note_text = (parsed.get("note") or "").strip()[:120]
                if note_text:
                    try:
                        supabase.table("thoughts").insert({"text": note_text}).execute()
                    except Exception:
                        pass
                args = {}
                if action == "write_thoughts":
                    args["text"] = (
                        parsed.get("parametr_one") or parsed.get("note") or ""
                    )
                if action == "write_email":
                    args["email"] = parsed.get("parametr_one", "") or parsed.get(
                        "param"
                    )
                    args["message"] = parsed.get("parametr_two", "")
                if action == "language_interpretator":
                    args["code"] = parsed.get("parametr_one", "") or parsed.get("param")
                if action == "fetch_news":
                    args["news_query"] = parsed.get("parametr_one", "") or parsed.get(
                        "param"
                    )
                res = call_local_function(action, args)
                memory.append({"role": "function", "name": action, "content": res})
            # подготовим next user message
            next_q = (
                parsed.get("next_q") or "Continue generating a short note and question."
            )
            memory.append({"role": "user", "content": next_q})
            messages = [{"role": "system", "content": SYSTEM_PROMPT}] + last_n_msgs(5)
            continue

        # 3) Ничего не распарсили — сохраняем assistant content и просим продолжать
        memory.append({"role": "assistant", "content": content or "<no content>"})
        memory.append(
            {
                "role": "user",
                "content": "Continue generating a short note and question.",
            }
        )
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + last_n_msgs(5)
        continue


if __name__ == "__main__":
    print(
        thinker_loop(
            "",
            iterations=12,
        )
    )
