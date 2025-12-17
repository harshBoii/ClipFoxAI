import uuid
from typing import TypedDict
from dotenv import load_dotenv
import os
from langgraph.graph import StateGraph, END 
from langgraph.types import interrupt
from langchain_google_genai import ChatGoogleGenerativeAI
from fpdf import FPDF
import os, json
from markdown import markdown
try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except Exception:
    WEASYPRINT_AVAILABLE = False
from fpdf import FPDF
from markdown import markdown
from weasyprint import HTML, CSS
import os
import requests, urllib.parse
from langgraph.checkpoint.memory import MemorySaver


load_dotenv()

if "GOOGLE_API_KEY" not in os.environ:
    raise ValueError("GOOGLE_API_KEY environment variable not set. Please set it before running.")

# Initialize LLM
llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro")

# --- Define Agent State ---

class TenureAgentState(TypedDict):
    agency_name: str
    tenure: str
    fee: str
    requirement_list: list[str]
    joining_date: str
    client_name:str
    company_name:str
    company_email:str
    company_mobile:str
    session_id: str
    validated: bool
    tenure_template: str
    generated_letter_text: str
    formatted_letter_text: str
    pdf_path: str
    email_draft: str
    formatted_output: str
    user_reviewed_text:str

# --- Define Graph Nodes ---

def collect_tenure_data(state: TenureAgentState) -> TenureAgentState:
    print("---NODE: COLLECT TENURE DATA---")
    state["validated"] = False
    return state


def validate_tenure_data(state: TenureAgentState) -> TenureAgentState:
    print("---NODE: VALIDATING TENURE DATA---")
    required_fields = ["agency_name", "tenure", "fee", "joining_date"]
    missing = [f for f in required_fields if not state.get(f)]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")
    state["validated"] = True
    return state



def compose_tenure_template(state: TenureAgentState) -> TenureAgentState:
    print("---NODE: COMPOSING TENURE TEMPLATE---")
    prompt = f"""
    Draft a well-structured professional template for a tenure offer letter.

    Agency: {state['agency_name']}
    Tenure: {state['tenure']}
    Fee: {state['fee']}
    Joining Date: {state['joining_date']}
    Requirements: {', '.join(state['requirement_list'])}
    client name : {state['client_name']}
    our company email : {state['company_name']}
    our company number : {state['company_mobile']}
    our company email : {state['company_email']}

    
    Keep it concise, logical, and use placeholders for personalization.
    """
    response = llm.invoke(prompt)
    state["tenure_template"] = response.content.strip()
    return state


def generate_tenure_letter(state: TenureAgentState,**kwargs) -> TenureAgentState:

    print("---NODE: GENERATING TENURE LETTER---")
    print(f"state is : {state['tenure_template']}" )
    print("======================================")

    # ✅ 2. If the user already provided reviewed text, use it
    if state.get("user_reviewed_text") != "":
        print("✅ Resumed with human-edited letter. Skipping regeneration.")
        state["generated_letter_text"] = state.get("user_reviewed_text")
        return state

    prompt = f"""
    Using the following draft template write professionally written tenure offer letter.
    ------IMPORTANT-------
    RESPOND WITH ONLY THE OFFER LETTER AND NO EXTRA TEXT FROM YOUR SIDE SHOULD BE IN RESPONSE
    Template:
    {state['tenure_template']}

    Agency: {state['agency_name']}
    Tenure: {state['tenure']}
    Fee: {state['fee']}
    Joining Date: {state['joining_date']}
    Requirements: {', '.join(state['requirement_list'])}
    client name : {state['client_name']}
    our company email : {state['company_name']}
    our company number : {state['company_mobile']}
    our company email : {state['company_email']}

    """
    response = llm.invoke(prompt)
    state["generated_letter_text"] = response.content.strip()
    print (state["generated_letter_text"])
    return state


def format_letter_output(state: TenureAgentState) -> TenureAgentState:
    """
    Formats the letter using the LLM and renders a professional, visually-rich PDF.
    Header: elegant, red + black (Coca-Cola style) with a triangular separator (not a straight line),
            dynamic logo / company name / address.
    Footer: compact contact line.
    Uses tasteful fonts (Playfair Display for headline, Montserrat for body) with fallbacks.
    """
    print("---NODE: FORMATTING LETTER OUTPUT (HTML + PDF)---")

    data={
        "letter_text": state["generated_letter_text"],
        "message": "Please review and edit the generated offer letter.",
    }
    state["user_reviewed_text"]=interrupt(data)


    # --- Step 1: Refine the letter content via LLM (polished Markdown) ---
    final_text = state.get("user_reviewed_text") or state.get("generated_letter_text")

    format_prompt = f"""
    Refine the following letter in a professional, polished tone using Markdown.
    Use **bold** for key phrases, *italics* for emphasis, and ### for section headers.
    Keep it visually structured and avoid monotony.
    RESPOND WITH ONLY THE OFFER LETTER CONTENT — NO extra explanation.
    
    Letter:
    {final_text}
    """
    formatted_response = llm.invoke(format_prompt)
    formatted_md = formatted_response.content.strip()
    state["formatted_letter_text"] = formatted_md

    # --- Step 2: Convert Markdown → HTML body ---
    html_body = markdown(formatted_md, extensions=["extra", "sane_lists"])

    # --- Step 3: Gather dynamic branding from state (with sensible defaults) ---
    company_name = state.get("company_name", "Company X")
    company_address = state.get(
        "company_address",
        "Rmz, Millenia Business Park, Campus 1A, No.143, Dr.M.G.R. Road, Perungudi, Chennai - 600096"
    )
    def inline_svg_from_url(url: str) -> str:
        """
        Fetches SVG from `url` and returns a data:image/svg+xml;utf8,<encoded> URI.
        Falls back to the original URL if fetch fails.
        """
        try:
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            svg_text = r.text
            return "data:image/svg+xml;utf8," + urllib.parse.quote(svg_text)
        except Exception:
            return url  # fallback to remote URL

    # usage inside your function
    if not state.get("company_logo"):
        # build UI-Avatars or DiceBear URL (as above)
        external_logo = f"https://ui-avatars.com/api/?name={urllib.parse.quote_plus(company_name)}&size=320&background=black&color=fff&bold=true&format=svg"
        logo_url = inline_svg_from_url(external_logo)
    else:
        logo_url = state["company_logo"]
    company_website = state.get("company_website", "AiInternational.com")
    contact_email = state.get("company_email", "AiInternational")
    session_id = state.get("session_id", "unknown")

    # Coca-Cola like red; main black; accents:
    red = state.get("company_color", "#C8102E")   # default rich red
    black = "#0b0b0b"

    # --- Step 4: Build header & footer HTML (dynamic) ---
    header_html = f"""
    <header class="letter-header" role="banner" aria-label="Letter header">
      <div class="header-left">
        <div class="logo-wrap">
          <img src="{logo_url}" alt="{company_name} logo" class="logo">
        </div>
        <div class="company-meta">
          <div class="company-name">{company_name}</div>
          <div class="company-address">{company_address}</div>
        </div>
      </div>

      <!-- triangular color block on the right -->
      <div class="header-right" aria-hidden="true"></div>
    </header>
    """

    footer_html = f"""
    <footer class="letter-footer" role="contentinfo">
      <div class="footer-left">© {company_name} • {company_website} • {contact_email}</div>
      <div class="footer-right">Document ID: {session_id}</div>
    </footer>
    """

    # --- Step 5: Compose a refined CSS with pretty fonts and triangular separator ---
    # Note: For best PDF font embedding, ensure your renderer can fetch Google Fonts or
    # provide local fonts. Fallbacks are included.
    css = f"""
/* Google fonts (used when renderer supports web fonts) */
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Montserrat:wght@300;400;600&display=swap');

@page {{
    size: A4;
    margin: 0;
}}

html, body {{
    width: 100%;
    min-height: 90%;
    margin: 0;
    padding: 0;
}}

body {{
    font-family: 'Montserrat', Arial, sans-serif;
    color: #111;
    line-height: 1.45;
    background: linear-gradient(180deg, #ffffff 0%, #fbfbfd 100%); /* subtle neutral page base */
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}}

/* ================= Header ================= */
.letter-header {{
    display: flex;
    align-items: stretch;
    height: 120px;
    width: 100%;
    position: relative;
    box-shadow: 0 6px 18px rgba(0,0,0,0.06);
    overflow: visible;
}}

/* Left side: black background containing logo + meta */
.header-left {{
    background: {black};
    color: #fff;
    display: flex;
    align-items: center;
    gap: 18px;
    padding: 18px 28px;
    min-width: 520px;          /* ensures nice left block presence for wide pages */
    box-sizing: border-box;
    
}}

/* Logo circle to look polished */
.logo-wrap {{
    width: 84px;
    height: 84px;
    border-radius: 8px;
    background: rgba(255,255,255,0.03);
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    flex-shrink: 0;
    box-shadow: 0 2px 6px rgba(0,0,0,0.3) inset;
}}

.logo {{
    max-width: 76px;
    max-height: 76px;
    object-fit: contain;
    display: block;
}}

/* Company text */
.company-meta {{
    display: flex;
    flex-direction: column;
    gap: 4px;
}}

.company-name {{
    font-family: 'Playfair Display', Georgia, 'Times New Roman', serif;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 0.6px;
    color: #fff;
}}

.company-address {{
    font-size: 12.5px;
    color: rgba(255,255,255,0.85);
    max-width: 420px;
    line-height: 1.25;
}}

/* Right side: red block with triangular separator (clip-path creates the triangle notch) */
.header-right {{
    flex: 1;
    background: {red};
    position: relative;
    /* create a diagonal triangular seam using clip-path */
    clip-path: polygon(8% 0%, 100% 0%, 100% 100%, 0% 100%);
}}

/* Add a subtle angled cut overlapping the left section to form a triangle seam */
.letter-header::after {{
    content: "";
    position: absolute;
    right: 0;
    top: 0;
    height: 120px;
    width: 160px;
    background: linear-gradient(135deg, rgba(0,0,0,0.04), rgba(255,255,255,0.02));
    transform: skewX(-18deg);
    box-shadow: -10px 0 20px rgba(0,0,0,0.08);
    pointer-events: none;
}}

/* ================= Content ================= */
.content {{
    padding: 46px 72px 120px 72px;
    background: transparent;
    z-index: 2;
    position: relative;
    box-sizing: border-box;
}}

h1, h2, h3 {{
    color: {black};
    font-family: 'Playfair Display', serif;
}}

h1 {{
    font-size: 20px;
    margin-bottom: 8px;
}}

p, li {{
    font-size: 13.5px;
    color: #111;
}}

/* strong/em emphasis */
strong {{
    color: {black};
    font-weight: 700;
}}

em {{
    color: #444;
    font-style: italic;
}}

/* ================= Watermark (subtle center) ================= */
body::before {{
    content: "{company_name}";
    position: fixed;
    top: 48%;
    left: 50%;
    transform: translate(-50%, -50%) rotate(-22deg);
    font-family: 'Playfair Display', serif;
    font-size: 96px;
    color: rgba(0,0,0,0.03);
    letter-spacing: 2px;
    white-space: nowrap;
    z-index: 0;
    pointer-events: none;
}}

/* Ensure header/footer stay above watermark */
body > * {{
    position: relative;
    z-index: 2;
}}

/* ================= Footer ================= */
.letter-footer {{
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 36px;
    font-size: 12px;
    color: #666;
    background: linear-gradient(180deg, rgba(255,255,255,0), rgba(255,255,255,0.95));
    border-top: 1px solid rgba(0,0,0,0.06);
    box-sizing: border-box;
}}

/* print adjustments */
@media print {{
    .letter-header {{ height: 110px; }}
    .logo-wrap {{ width: 72px; height: 72px; }}
    .company-name {{ font-size: 20px; }}
    .content {{ padding-top: 40px; padding-bottom: 80px; }}
    body::before {{ font-size: 80px; }}
}}
    """

    # --- Step 6: Assemble full HTML ---
    html_full = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <!-- Google Fonts (if renderer supports them) -->
    <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Montserrat:wght@300;400;600&display=swap" rel="stylesheet">
    <style>{css}</style>
  </head>
  <body>
    {header_html}
    <main class="content">
      {html_body}
    </main>
    {footer_html}
  </body>
</html>
"""

    # --- Step 7: Export to PDF (same approach as before) ---
    output_dir = "files"
    os.makedirs(output_dir, exist_ok=True)
    pdf_path = f"{output_dir}/tenure_letter_{session_id}.pdf"
    url_path= f"/tenure_letter_{session_id}.pdf"
    # Note: Some HTML->PDF renderers may not fetch Google fonts by default.
    # If your renderer has trouble, provide local font files or preload fonts into the renderer.
    HTML(string=html_full).write_pdf(pdf_path, stylesheets=[CSS(string=css)])
    print(f"✅ PDF generated (polished header & footer) at: {pdf_path}")
    base_url = "https://createos.vercel.app/admin/contract/view"

    state["pdf_path"] = f"{base_url}/{pdf_path}"
    return state


def generate_email_draft(state: TenureAgentState) -> TenureAgentState:
    print("---NODE: GENERATING EMAIL DRAFT---")
    prompt = f"""
    Write an email draft for sending the attached tenure offer letter to the client.
    ------IMPORTANT-------
    RESPOND WITH ONLY THE EMAIL DRAFT AND NO EXTRA TEXT FROM YOUR SIDE SHOULD BE IN RESPONSE

    Details:
    Agency: {state['agency_name']}
    Tenure: {state['tenure']}
    Fee: {state['fee']}
    Joining Date: {state['joining_date']}
    Requirements: {', '.join(state['requirement_list'])}
    client name : {state['client_name']}
    our company email : {state['company_name']}
    our company number : {state['company_mobile']}
    our company email : {state['company_email']}

    The email should be professional, polite, and reference the attached PDF.
    """
    response = llm.invoke(prompt)
    state["email_draft"] = response.content.strip()
    return state


def attach_offer_pdf(state: TenureAgentState) -> TenureAgentState:
    print("---NODE: ATTACH OFFER PDF---")

    url_path= f"tenure_letter_{state.get("session_id")}.pdf"
    base_url = "https://createos.vercel.app/admin/contract/view"

    attachment_note = f"\n\n[Attachment: {f"{base_url}/{url_path}"}]"
    state["email_draft"] += attachment_note
    return state


def return_response(state: TenureAgentState) -> TenureAgentState:
    print("---NODE: RETURN RESPONSE---")
    summary = (
        f"✅ Tenure letter and email draft generated successfully.\n"
        f"Agency: {state.get('agency_name')}\n"
        f"PDF Path: {state.get('pdf_path')}\n\n"
        f"Email Preview:\n\n{state.get('email_draft')}"
    )
    state["formatted_output"] = summary

    # Add structured final_response dict (json-serializable)
    state["final_response"] = {
        "summary": summary,
        "pdf_path": state.get("pdf_path"),
        "email_draft_markdown": state.get("email_draft"),
        "letter_markdown": state.get("formatted_letter_text")
    }
    return state

# --- Build Graph Flow ---
memory = MemorySaver()
workflow = StateGraph(TenureAgentState)

workflow.add_node("collect_tenure_data", collect_tenure_data)
workflow.add_node("validate_tenure_data", validate_tenure_data)
workflow.add_node("compose_tenure_template", compose_tenure_template)
workflow.add_node("generate_tenure_letter", generate_tenure_letter)
workflow.add_node("format_letter_output", format_letter_output)
workflow.add_node("generate_email_draft", generate_email_draft)
workflow.add_node("attach_offer_pdf", attach_offer_pdf)
workflow.add_node("return_response", return_response)

workflow.set_entry_point("collect_tenure_data")
workflow.add_edge("collect_tenure_data", "validate_tenure_data")
workflow.add_edge("validate_tenure_data", "compose_tenure_template")
workflow.add_edge("compose_tenure_template", "generate_tenure_letter")
workflow.add_edge("generate_tenure_letter", "format_letter_output")
workflow.add_edge("format_letter_output", "generate_email_draft")
workflow.add_edge("generate_email_draft", "attach_offer_pdf")
workflow.add_edge("attach_offer_pdf", "return_response")
workflow.add_edge("return_response", END)

agency_agent_app = workflow.compile(checkpointer=memory)


