#botox  
import streamlit as st
import requests
import json
import html
import markdown
from openai import OpenAI
from datetime import datetime

# ---------------------------------
# PAGE CONFIG
# ---------------------------------

st.set_page_config(
    page_title="Lucie's OpenAlex AI Agent Sandbox",
    page_icon="🤖",
    layout="wide"
)


# ---------------------------------
# CONSTANTS
# ---------------------------------

CURRENT_YEAR = datetime.now().year


CURRENT_YEAR = datetime.now().year


SYSTEM_MESSAGE = {
    "role": "system",
    "content": f"""
You are a journal editor assistant with access to the OpenAlex API.

CURRENT DATE CONTEXT
The current year is {CURRENT_YEAR}.
Interpret relative dates using this year:
- this year = {CURRENT_YEAR}
- last year = {CURRENT_YEAR - 1}
- next year = {CURRENT_YEAR + 1}

OPENALEX OPERATING RULES
When factual literature data is required, use the OpenAlex tool.

Your job is to translate the user's request into an OpenAlex API
query plan. Construct the endpoint and query parameters yourself
using valid classic OpenAlex API syntax.

For this first implementation, use only the "works" endpoint.

SUPPORTED PARAMETERS
- search: broad text search across title, abstract and available full text
- filter: OpenAlex filter expression
- sort: OpenAlex sort expression
- select: comma-separated response fields
- per_page: number of results
- page: page number

FILTER SYNTAX
- Combine different conditions with commas. This means AND.
- Examples:
  publication_year:2025
  from_publication_date:2020-01-01
  to_publication_date:2025-12-31
  type:review
  is_oa:true
  cited_by_count:>50
  title.search:lipid rafts
  title.search.no_stem:lipid rafts
  abstract.search:cellular senescence
  title_and_abstract.search:cellular senescence

SEARCH RULES
- Use search for a broad relevance search.
- If the user explicitly requires text in the title, use
  title.search inside filter. Do not use broad search.
- If the user explicitly requires text in the abstract, use
  abstract.search inside filter.
- If the user asks for title or abstract searching, use
  title_and_abstract.search.
- Use .no_stem only when the user explicitly requires literal,
  unstemmed matching.
- Boolean operators AND, OR and NOT must be uppercase.
- Use quotation marks in a search expression when the user clearly
  requires an exact multi-word phrase.

SORTING RULES
- "Highly cited", "most cited" or "top cited":
  cited_by_count:desc
- "Newest" or "most recent":
  publication_date:desc
- "Oldest":
  publication_date:asc
- Do not sort by publication date unless the user requests a
  chronological preference.

RESULT COUNT
Set per_page to the number requested by the user.
If no number is requested, use 5.

DEFAULT SELECT
Unless additional fields are needed, use:
id,title,doi,publication_year,publication_date,cited_by_count,type

SAMPLE QUERY PLANS

User:
Give me three highly cited papers with "lipid rafts" in the title
published last year.

Plan:
endpoint = works
filter = title.search:"lipid rafts",publication_year:{CURRENT_YEAR - 1}
sort = cited_by_count:desc
per_page = 3
select = id,title,doi,publication_year,publication_date,cited_by_count,type

User:
Find five recent review papers about cellular senescence since 2022.

Plan:
endpoint = works
search = cellular senescence
filter = type:review,from_publication_date:2022-01-01
sort = publication_date:desc
per_page = 5
select = id,title,doi,publication_year,publication_date,cited_by_count,type

User:
Find open-access papers about autophagy published in 2024.

Plan:
endpoint = works
search = autophagy
filter = publication_year:2024,is_oa:true
per_page = 5
select = id,title,doi,publication_year,publication_date,cited_by_count,type,is_oa

IMPORTANT
- Never invent OpenAlex results.
- Never claim a returned record satisfies a condition without checking
  the returned metadata.
- Explain unsuccessful or empty searches honestly.
- The application adds the API key. Never include an API key in the
  query plan.
- Do not construct a complete external URL. Supply only the endpoint
  and query parameters through the tool.
"""
}


# ---------------------------------
# SESSION STATE INITIALIZATION
# ---------------------------------

if "OPENAI_API_KEY" not in st.session_state:
    st.session_state.OPENAI_API_KEY = ""

if "OPENALEX_API_KEY" not in st.session_state:
    st.session_state.OPENALEX_API_KEY = ""

if "agent_messages" not in st.session_state:
    st.session_state.agent_messages = [SYSTEM_MESSAGE.copy()]

if "response_counter" not in st.session_state:
    st.session_state.response_counter = 0

if "MAX_HISTORY" not in st.session_state:
    st.session_state.MAX_HISTORY = 80



# ---------------------------------
# HELPERS
# ---------------------------------



##
def get_messages_for_model():
    """
    Return only the most recent messages that should
    be sent to the AI.
    """

    if len(st.session_state.agent_messages) <= 1:
        return st.session_state.agent_messages

    system_prompt = st.session_state.agent_messages[0]

    recent_messages = st.session_state.agent_messages[
        -st.session_state.MAX_HISTORY:
    ]

    return [system_prompt] + recent_messages
##


def markdown_to_html(content):
    """
    Convert Markdown text into formatted HTML.

    Escaping first prevents raw HTML returned by the model
    from being inserted directly into the downloaded file.
    Markdown formatting and links are still preserved.
    """

    if content is None:
        return ""

    safe_content = html.escape(str(content))

    return markdown.markdown(
        safe_content,
        extensions=[
            "tables",
            "fenced_code",
            "sane_lists"
        ]
    )


def get_export_css():
    """
    Shared styling for individual-response and full-thread exports.
    """

    return """
        body {
            font-family: Arial, Helvetica, sans-serif;
            max-width: 1100px;
            margin: 40px auto;
            padding: 20px;
            line-height: 1.65;
            color: #222222;
            background-color: #ffffff;
        }

        h1 {
            color: #1f77b4;
            border-bottom: 2px solid #1f77b4;
            padding-bottom: 10px;
        }

        h2, h3, h4 {
            color: #333333;
        }

        a {
            color: #0068c9;
        }

        .message {
            margin: 20px 0;
            padding: 18px;
            border-radius: 8px;
        }

        .user {
            background-color: #eef6ff;
            border-left: 5px solid #2b7de9;
        }

        .assistant {
            background-color: #f2fbf1;
            border-left: 5px solid #2ca02c;
        }

        .tool-call {
            background-color: #fff8e8;
            border-left: 5px solid #f2a900;
        }

        .tool-result {
            background-color: #f5f5f5;
            border-left: 5px solid #777777;
        }

        .role-label {
            margin-bottom: 12px;
            font-size: 0.85rem;
            font-weight: bold;
            text-transform: uppercase;
            color: #555555;
        }

        pre {
            white-space: pre-wrap;
            overflow-wrap: anywhere;
            background-color: #f6f8fa;
            border: 1px solid #dddddd;
            border-radius: 6px;
            padding: 12px;
        }

        code {
            font-family: Consolas, Monaco, monospace;
        }

        table {
            border-collapse: collapse;
            width: 100%;
            margin: 16px 0;
        }

        th, td {
            border: 1px solid #dddddd;
            padding: 8px;
            text-align: left;
            vertical-align: top;
        }

        th {
            background-color: #f2f2f2;
        }

        blockquote {
            border-left: 4px solid #cccccc;
            margin-left: 0;
            padding-left: 15px;
            color: #555555;
        }

        .footer {
            margin-top: 40px;
            padding-top: 15px;
            border-top: 1px solid #dddddd;
            color: #777777;
            font-size: 0.85rem;
        }
    """


def create_individual_html_export(content):
    """
    Create an HTML document containing one assistant response.
    """

    formatted_content = markdown_to_html(content)

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>OpenAlex Agent Output</title>

        <style>
            {get_export_css()}
        </style>
    </head>

    <body>
        <h1>OpenAlex Agent Output</h1>

        <div class="message assistant">
            {formatted_content}
        </div>

        <div class="footer">
            Generated with Lucie's OpenAlex AI Agent Sandbox
        </div>
    </body>
    </html>
    """


def format_tool_arguments(tool_call):
    """
    Extract and format the arguments from an OpenAI tool call.
    """

    try:
        function_data = tool_call.get("function", {})
        function_name = function_data.get("name", "Unknown tool")
        raw_arguments = function_data.get("arguments", "{}")

        try:
            parsed_arguments = json.loads(raw_arguments)
            formatted_arguments = json.dumps(
                parsed_arguments,
                indent=2,
                ensure_ascii=False
            )
        except (json.JSONDecodeError, TypeError):
            formatted_arguments = str(raw_arguments)

        return function_name, formatted_arguments

    except Exception:
        return "Unknown tool", str(tool_call)


def create_full_conversation_html():
    """
    Create an HTML export of the complete conversation.

    Includes:
    - user queries
    - assistant responses
    - tool-call parameters
    - raw OpenAlex tool results

    Excludes:
    - system prompt
    - API keys
    """

    conversation_sections = []

    for message in st.session_state.agent_messages:

        role = message.get("role")
        content = message.get("content")

        # Do not export the internal system prompt
        if role == "system":
            continue

        if role == "user" and content:
            conversation_sections.append(
                f"""
                <div class="message user">
                    <div class="role-label">User query</div>
                    {markdown_to_html(content)}
                </div>
                """
            )

        elif role == "assistant":

            # Some assistant messages contain tool calls but no text
            tool_calls = message.get("tool_calls") or []

            for tool_call in tool_calls:
                function_name, formatted_arguments = (
                    format_tool_arguments(tool_call)
                )

                safe_function_name = html.escape(function_name)
                safe_arguments = html.escape(formatted_arguments)

                conversation_sections.append(
                    f"""
                    <div class="message tool-call">
                        <div class="role-label">
                            Agent tool call: {safe_function_name}
                        </div>
                        <pre><code>{safe_arguments}</code></pre>
                    </div>
                    """
                )

            if content:
                conversation_sections.append(
                    f"""
                    <div class="message assistant">
                        <div class="role-label">Assistant response</div>
                        {markdown_to_html(content)}
                    </div>
                    """
                )

        elif role == "tool":

            tool_name = message.get(
                "name",
                "OpenAlex tool response"
            )

            safe_tool_name = html.escape(str(tool_name))
            safe_tool_content = html.escape(str(content or ""))

            conversation_sections.append(
                f"""
                <div class="message tool-result">
                    <div class="role-label">
                        Raw tool result: {safe_tool_name}
                    </div>
                    <pre><code>{safe_tool_content}</code></pre>
                </div>
                """
            )

    if not conversation_sections:
        conversation_sections.append(
            """
            <p>No conversation has been recorded yet.</p>
            """
        )

    conversation_body = "\n".join(conversation_sections)

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>OpenAlex Agent Full Conversation</title>

        <style>
            {get_export_css()}
        </style>
    </head>

    <body>
        <h1>OpenAlex Agent Conversation</h1>

        {conversation_body}

        <div class="footer">
            Full conversation and debugging export from
            Lucie's OpenAlex AI Agent Sandbox.
            API keys and the internal system prompt are not included.
        </div>
    </body>
    </html>
    """


def clear_conversation():
    """
    Clear the conversation while retaining API keys.
    """

    st.session_state.agent_messages = [SYSTEM_MESSAGE.copy()]
    st.session_state.response_counter = 0


# ---------------------------------
# SIDEBAR: API KEYS
# ---------------------------------

with st.sidebar:

    st.header("🔑 API Keys")

    st.text_input(
        "OpenAI API Key",
        type="password",
        key="OPENAI_API_KEY",
        help="Enter your OpenAI API key."
    )

    st.text_input(
        "OpenAlex API Key",
        type="password",
        key="OPENALEX_API_KEY",
        help="Enter your OpenAlex API key."
    )

    st.divider()

    st.header("🧠 AI Context Window")

    st.session_state.MAX_HISTORY = st.number_input(
        "Messages sent to the AI",
        min_value=5,
        max_value=500,
        value=st.session_state.MAX_HISTORY,
        step=5,
        help="""
The full conversation is always stored.

This setting controls how many recent messages
are sent back to the AI when generating the next reply.

Higher values:
• Better memory
• Higher token usage

Lower values:
• Lower token usage
• Earlier discussion may stop influencing answers

All messages remain visible and downloadable.
"""
    )

    #visible_messages = max(
    #    0,
    #    len(st.session_state.agent_messages) - 1
    #)

    stored_messages = len(st.session_state.agent_messages)

    visible_messages = sum(
        1
        for m in st.session_state.agent_messages
        if (
            m.get("role") in ["user", "assistant"]
            and m.get("content")
        )
    )

    st.info(
        f"""
    Conversation contains {visible_messages} visible messages.

    The AI currently receives {stored_messages} context records
    (user messages, assistant messages, tool calls and tool results).
    """
    )




# ---------------------------------
# OPENAI CLIENT
# ---------------------------------

client = None

if st.session_state.OPENAI_API_KEY:
    try:
        client = OpenAI(
            api_key=st.session_state.OPENAI_API_KEY
        )
    except Exception as error:
        st.error(
            f"Could not initialize the OpenAI client: {error}"
        )


# ---------------------------------
# OPENALEX TOOL FUNCTION
# ---------------------------------

# ---------------------------------
# OPENALEX QUERY EXECUTOR
# ---------------------------------

ALLOWED_OPENALEX_ENDPOINTS = {
    "works"
}

ALLOWED_OPENALEX_PARAMETERS = {
    "search",
    "filter",
    "sort",
    "select",
    "per_page",
    "page"
}

DEFAULT_SELECT = (
    "id,title,doi,publication_year,"
    "publication_date,cited_by_count,type"
)

MAX_PER_PAGE = 25
MAX_PARAMETER_LENGTH = 4000


def validate_openalex_query_plan(
    endpoint: str,
    params: dict
):
    """
    Validate an AI-generated OpenAlex query plan.

    The model constructs the query, but the application controls:
    - the OpenAlex host
    - allowed endpoints
    - allowed parameters
    - API-key insertion
    - result limits
    """

    if not isinstance(endpoint, str):
        raise ValueError(
            "The OpenAlex endpoint must be a string."
        )

    endpoint = endpoint.strip().lower().strip("/")

    if endpoint not in ALLOWED_OPENALEX_ENDPOINTS:
        raise ValueError(
            f"Unsupported OpenAlex endpoint: {endpoint}. "
            "This version currently supports only 'works'."
        )

    if not isinstance(params, dict):
        raise ValueError(
            "OpenAlex query parameters must be an object."
        )

    validated_params = {}

    for key, value in params.items():

        if key not in ALLOWED_OPENALEX_PARAMETERS:
            raise ValueError(
                f"Unsupported OpenAlex parameter: {key}"
            )

        if value is None or value == "":
            continue

        if key in {"per_page", "page"}:

            try:
                numeric_value = int(value)
            except (TypeError, ValueError):
                raise ValueError(
                    f"Parameter '{key}' must be an integer."
                )

            if key == "per_page":
                numeric_value = max(
                    1,
                    min(numeric_value, MAX_PER_PAGE)
                )

            if key == "page":
                numeric_value = max(1, numeric_value)

            validated_params[key] = numeric_value

        else:

            if not isinstance(value, str):
                raise ValueError(
                    f"Parameter '{key}' must be a string."
                )

            cleaned_value = value.strip()

            if not cleaned_value:
                continue

            if len(cleaned_value) > MAX_PARAMETER_LENGTH:
                raise ValueError(
                    f"Parameter '{key}' is too long."
                )

            if "\n" in cleaned_value or "\r" in cleaned_value:
                raise ValueError(
                    f"Parameter '{key}' contains invalid "
                    "line-break characters."
                )

            validated_params[key] = cleaned_value

    if (
        "search" not in validated_params
        and "filter" not in validated_params
    ):
        raise ValueError(
            "The query plan must contain at least a "
            "'search' or 'filter' parameter."
        )

    if "per_page" not in validated_params:
        validated_params["per_page"] = 5

    if "select" not in validated_params:
        validated_params["select"] = DEFAULT_SELECT

    return endpoint, validated_params


def execute_openalex_query(
    endpoint: str,
    params: dict
) -> str:
    """
    Validate and execute an AI-generated OpenAlex query plan.
    """

    if not st.session_state.OPENALEX_API_KEY:
        return "Error: OpenAlex API key not provided."

    try:
        endpoint, validated_params = (
            validate_openalex_query_plan(
                endpoint=endpoint,
                params=params
            )
        )

    except ValueError as error:
        return (
            "Error: The generated OpenAlex query plan "
            f"did not pass validation. {str(error)}"
        )

    url = f"https://api.openalex.org/{endpoint}"

    request_params = dict(validated_params)

    # The application adds the key. The AI never sees or supplies it.
    request_params["api_key"] = (
        st.session_state.OPENALEX_API_KEY
    )

    try:
        headers = {
            "User-Agent": "Lucies-OpenAlex-Agent-Sandbox"
        }

        response = requests.get(
            url,
            headers=headers,
            params=request_params,
            timeout=30
        )

        # Generate a readable request URL without the API key.
        safe_prepared_request = requests.Request(
            method="GET",
            url=url,
            params=validated_params
        ).prepare()

        safe_request_url = safe_prepared_request.url

        print("\n--- DEBUG OPENALEX REQUEST ---")
        print(f"Request URL: {safe_request_url}")
        print(f"HTTP status: {response.status_code}")
        print("--------------------------------\n")

        if response.status_code == 200:

            data = response.json()

            return json.dumps(
                {
                    "executed_request": {
                        "endpoint": endpoint,
                        "params": validated_params,
                        "url_without_api_key": (
                            safe_request_url
                        )
                    },
                    "meta": data.get("meta", {}),
                    "results": data.get("results", [])
                },
                indent=2,
                ensure_ascii=False
            )

        return json.dumps(
            {
                "executed_request": {
                    "endpoint": endpoint,
                    "params": validated_params,
                    "url_without_api_key": (
                        safe_request_url
                    )
                },
                "error": {
                    "status_code": response.status_code,
                    "response": response.text
                }
            },
            indent=2,
            ensure_ascii=False
        )

    except requests.exceptions.Timeout:
        return (
            "Error: The OpenAlex request timed out "
            "after 30 seconds."
        )

    except requests.exceptions.RequestException as error:
        return (
            "Error connecting to OpenAlex: "
            f"{str(error)}"
        )

    except Exception as error:
        return (
            "Unexpected error while processing the "
            f"OpenAlex response: {str(error)}"
        )

# ---------------------------------
# OPENAI TOOL SCHEMA
# ---------------------------------

# ---------------------------------
# OPENAI TOOL SCHEMA
# ---------------------------------

OPENALEX_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_openalex_query",
        "description": (
            "Execute a dynamically constructed OpenAlex API "
            "query plan. Translate the user's literature request "
            "into a valid OpenAlex endpoint and query parameters. "
            "For this version, use the works endpoint."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "endpoint": {
                    "type": "string",
                    "description": (
                        "The OpenAlex entity endpoint."
                    ),
                    "enum": [
                        "works"
                    ]
                },
                "params": {
                    "type": "object",
                    "description": (
                        "The OpenAlex query parameters constructed "
                        "from the user's request."
                    ),
                    "properties": {
                        "search": {
                            "type": "string",
                            "description": (
                                "Broad text search across titles, "
                                "abstracts and available full text."
                            )
                        },
                        "filter": {
                            "type": "string",
                            "description": (
                                "A valid OpenAlex filter expression, "
                                "for example "
                                "'title.search:lipid rafts,"
                                "publication_year:2025'."
                            )
                        },
                        "sort": {
                            "type": "string",
                            "description": (
                                "A valid OpenAlex sort expression, "
                                "for example "
                                "'cited_by_count:desc'."
                            )
                        },
                        "select": {
                            "type": "string",
                            "description": (
                                "Comma-separated OpenAlex fields "
                                "to return."
                            )
                        },
                        "per_page": {
                            "type": "integer",
                            "description": (
                                "Number of results requested."
                            ),
                            "minimum": 1,
                            "maximum": 25,
                            "default": 5
                        },
                        "page": {
                            "type": "integer",
                            "description": (
                                "Page number to retrieve."
                            ),
                            "minimum": 1,
                            "default": 1
                        }
                    },
                    "additionalProperties": False
                }
            },
            "required": [
                "endpoint",
                "params"
            ],
            "additionalProperties": False
        }
    }
}


# ---------------------------------
# APP HEADER
# ---------------------------------

st.header("🤖 Lucie's OpenAlex AI Agent Sandbox; with very limited capability")

st.write(
    "Ask the AI to search OpenAlex, find papers, "
    "evaluate topics, and explore the literature."
)


# ---------------------------------
# DISPLAY EXISTING CHAT HISTORY
# ---------------------------------

assistant_display_number = 0

for message in st.session_state.agent_messages:

    role = message.get("role")
    content = message.get("content")

    if role == "user" and content:

        with st.chat_message("user"):
            st.markdown(content)

    elif role == "assistant" and content:

        assistant_display_number += 1

        with st.chat_message("assistant"):

            st.markdown(content)

            individual_html = (
                create_individual_html_export(content)
            )

            st.download_button(
                label="📥 Download this response",
                data=individual_html,
                file_name=(
                    "openalex_agent_output_"
                    f"{assistant_display_number}.html"
                ),
                mime="text/html",
                key=(
                    "historic_download_"
                    f"{assistant_display_number}"
                )
            )


# ---------------------------------
# CHAT INPUT
# ---------------------------------

user_prompt = st.chat_input(
    "What would you like to check in OpenAlex?"
)

if user_prompt:

    if not st.session_state.OPENAI_API_KEY:
        st.error(
            "Please enter your OpenAI API key "
            "in the sidebar."
        )
        st.stop()

    if not st.session_state.OPENALEX_API_KEY:
        st.error(
            "Please enter your OpenAlex API key "
            "in the sidebar."
        )
        st.stop()

    if client is None:
        st.error(
            "The OpenAI client could not be initialized."
        )
        st.stop()

    with st.chat_message("user"):
        st.markdown(user_prompt)

    st.session_state.agent_messages.append(
        {
            "role": "user",
            "content": user_prompt
        }
    )

    with st.chat_message("assistant"):

        with st.spinner("Thinking..."):

            try:
                # ---------------------------------
                # PASS 1: MODEL DECIDES WHETHER
                # TO CALL OPENALEX
                # ---------------------------------

                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=get_messages_for_model(),
                    tools=[OPENALEX_TOOL],
                    tool_choice="auto"
                )

                response_message = response.choices[0].message

                # Convert the OpenAI message object into
                # a standard dictionary for session storage.
                response_message_dict = response_message.model_dump(
                    exclude_none=True
                )

                st.session_state.agent_messages.append(
                    response_message_dict
                )

                # ---------------------------------
                # TOOL CALL HANDLING
                # ---------------------------------

                if response_message.tool_calls:

                    for tool_call in response_message.tool_calls:

                        
                        if (
                            tool_call.function.name
                            == "execute_openalex_query"
                        ):

                            try:
                                arguments = json.loads(
                                    tool_call.function.arguments
                                )

                            except json.JSONDecodeError:

                                tool_output = (
                                    "Error: The agent generated "
                                    "invalid tool arguments."
                                )

                                arguments = {}

                            else:
                                st.caption(
                                    "🔍 Agent-generated OpenAlex query plan:"
                                )

                                st.code(
                                    json.dumps(
                                        arguments,
                                        indent=2,
                                        ensure_ascii=False
                                    ),
                                    language="json"
                                )

                                tool_output = execute_openalex_query(
                                    endpoint=arguments.get(
                                        "endpoint"
                                    ),
                                    params=arguments.get(
                                        "params",
                                        {}
                                    )
                                )

                            st.session_state.agent_messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": (
                                        "execute_openalex_query"
                                    ),
                                    "content": tool_output
                                }
                            )

                    # ---------------------------------
                    # PASS 2: MODEL INTERPRETS
                    # OPENALEX RESULTS
                    # ---------------------------------

                    second_response = (
                        client.chat.completions.create(
                            model="gpt-4o",
                            messages=get_messages_for_model()
                        )
                    )


                    final_text = (
                        second_response
                        .choices[0]
                        .message
                        .content
                    )

                    if not final_text:
                        final_text = (
                            "The agent did not return a "
                            "text response."
                        )

                    st.session_state.agent_messages.append(
                        {
                            "role": "assistant",
                            "content": final_text
                        }
                    )

                # ---------------------------------
                # NO TOOL CALL REQUIRED
                # ---------------------------------

                elif response_message.content:

                    final_text = response_message.content

                    # The first-pass assistant message is
                    # already present in agent_messages.
                    # Do not append it a second time.

                else:
                    final_text = (
                        "The agent did not return a response."
                    )

                    st.session_state.agent_messages.append(
                        {
                            "role": "assistant",
                            "content": final_text
                        }
                    )

                # ---------------------------------
                # DISPLAY NEW RESPONSE
                # ---------------------------------

                st.markdown(final_text)

                st.session_state.response_counter += 1

                new_response_html = (
                    create_individual_html_export(final_text)
                )

                st.download_button(
                    label="📥 Download this response",
                    data=new_response_html,
                    file_name=(
                        "openalex_agent_output_"
                        f"{assistant_display_number + 1}.html"
                    ),
                    mime="text/html",
                    key=(
                        "new_download_"
                        f"{st.session_state.response_counter}"
                    )
                )

            except Exception as error:

                error_message = (
                    "An error occurred while processing "
                    f"the request: {str(error)}"
                )

                st.error(error_message)

                # Store the visible error in the thread so it
                # remains available after a Streamlit rerun.
                st.session_state.agent_messages.append(
                    {
                        "role": "assistant",
                        "content": error_message
                    }
                )


# ---------------------------------
# SIDEBAR: CONVERSATION MANAGEMENT
# ---------------------------------
# This is deliberately rendered after chat processing so that
# the full-thread download immediately includes the newest turn.

with st.sidebar:

    st.divider()
    st.header("💬 Conversation")

    full_conversation_html = (
        create_full_conversation_html()
    )

    st.download_button(
        label="📥 Download full thread",
        data=full_conversation_html,
        file_name="openalex_agent_full_conversation.html",
        mime="text/html",
        key="download_full_conversation",
        use_container_width=True
    )

    st.button(
        "🗑️ Clear conversation",
        on_click=clear_conversation,
        use_container_width=True
    )
