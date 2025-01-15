import os
import base64
import json
import time
from openai import OpenAI
from dotenv import load_dotenv
import re
import argparse

def set_file_path(paths, analysis=None):
    """
    Sets the file paths and optional analysis file dynamically.
    """
    global file_paths, analysis_file
    file_paths = paths
    analysis_file = analysis

def load_environment_variables():
    load_dotenv()

def initialize_openai_client():
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def create_assistant(client):
    return client.beta.assistants.create(
        name="Financial Analyst Assistant",
        instructions="You are an expert financial analyst. Use your knowledge base to answer questions about audited financial statements.",
        model="gpt-4o-mini",
        tools=[{"type": "file_search"}]
    )

def create_vector_store(client):
    return client.beta.vector_stores.create(name="Financial Statements")

def upload_files_to_vector_store(client, vector_store, file_paths):
    file_streams = [open(path, "rb") for path in file_paths]
    file_batch = client.beta.vector_stores.file_batches.upload_and_poll(
        vector_store_id=vector_store.id,
        files=file_streams
    )
    for stream in file_streams:
        stream.close()
    return file_batch

def update_assistant_with_vector_store(client, assistant, vector_store):
    client.beta.assistants.update(
        assistant_id=assistant.id,
        tool_resources={"file_search": {"vector_store_ids": [vector_store.id]}}
    )

def create_thread(client, assistant):
    return client.beta.threads.create(
        messages=[
            {
                "role": "user",
                "content": (
                    """We are going to analyze the accounts, transactions, and fraud information of a user to determine if the user has committed a financial crime. There will be an assistant and a user; the user will ask questions from the narrative questions list. The assistant will interpret these questions, look for supporting data in the uploaded files, and build an answer using that data."""
                )
            }
        ]
    )

def run_assistant(client, assistant_id, thread_id, user_instructions):
    run = client.beta.threads.runs.create_and_poll(
        thread_id=thread_id,
        assistant_id=assistant_id,
        instructions=user_instructions
    )
    return wait_on_run(client, run, thread_id)

def wait_on_run(client, run, thread_id):
    while run.status in ["queued", "in_progress"]:
        time.sleep(0.5)
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
    return run

def process_questions(client, assistant, thread, patterns):
    for ques in patterns:
        # Post the question to the thread
        client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=ques
        )

        # Ask the assistant to answer, referencing the file search data
        run = run_assistant(
            client,
            assistant.id,
            thread.id,
            (
                "Identify yourself as a financial statement analyst. The files contain analysis about a bank customer's "
                "transactions. We have to build a final narrative that concludes whether a financial crime has been committed. "
                "Answer the question by referencing the file search data where relevant."
                "finally mention a confidence score in percentage out of 100, that tells me how much is the analysis data from your search is supporting the answer to the question, the percentage is a holistic overview of how much the gathered information supports our question."
            )
        )

        # Retrieve all messages in this run
        messages = list(client.beta.threads.messages.list(thread_id=thread.id, run_id=run.id))
        message_content = messages[0].content[0].text  # The assistant's response
        annotations = message_content.annotations
        citations = []

        # Example: replace annotation text with bracket references, build citations list
        for index, annotation in enumerate(annotations):
            message_content.value = message_content.value.replace(annotation.text, f"[{index}]")
            if file_citation := getattr(annotation, "file_citation", None):
                cited_file = client.files.retrieve(file_citation.file_id)
                citations.append(f"[{index}] {cited_file.filename}")

        print(message_content.value)
        print("\n".join(citations))

########################################################################
# New: Wrap entire logic in a function that can also accept the analysis file
########################################################################
def run_narrative_workflow(client,assistant,thread):

    # Your original "patterns" or narrative questions
    patterns = [
        "What rule(s) did the alert generate for?",
        "What is the Card/Account Program?",
        "What is the Card/Account program description?",
        "What is the primary cause(s) for the alerting activity?",
        "What are other major credit(s) to the account?",
        "What are other major debit(s) to the account?",
        "What is the overall flow of funds through this account?",
        "Is activity occurring in/near Cardholder's residing area?",
        "Is the expected activity showing a spike or fairly consistent?",
        "Are there any additional red flags to address and can they be mitigated?",
        "Should this alert be escalated or closed as non-issue?",
    ]

    process_questions(client, assistant, thread, patterns)

def save_narrative_to_file(narrative_text, output_file="output_narrative.txt"):
    with open(output_file, "w") as file:
        file.write(narrative_text)
    print(f"Narrative saved to {output_file}")

############################
# Keep your original main
############################
def execute_narrative_workflow(files, analysis_file=None):
    """
    Executes the narrative workflow without relying on argparse.
    """
    all_files = list(files)
    if analysis_file and os.path.isfile(analysis_file):
        all_files.append(analysis_file)

    load_environment_variables()
    client = initialize_openai_client()
    assistant = create_assistant(client)
    vector_store = create_vector_store(client)

    # Upload all files (original + analysis) to vector store
    file_batch = upload_files_to_vector_store(client, vector_store, all_files)
    print("File batch status:", file_batch.status)
    print("File batch counts:", file_batch.file_counts)

    update_assistant_with_vector_store(client, assistant, vector_store)

    thread = create_thread(client, assistant)
    print("Thread resources:", thread.tool_resources.file_search)

    run_narrative_workflow(client,assistant,thread)

    ques=""" You are tasked with creating an AML narrative based on comprehensive inputs, including summaries from machine learning algorithms, a UAR report, and answers to investigative questions related to flagged account or card activity. Assume the perspective of a seasoned FCRM analyst and craft a narrative in a factual, neutral tone, structured in essay format without labeled sections. The narrative should be data-driven and logical, reflecting a thorough analytical approach."""

    client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=ques
        )

        # Ask the assistant to answer, referencing the file search data
    run = run_assistant(
            client,
            assistant.id,
            thread.id,
            (
                "Identify yourself as a financial statement analyst. you have already answered the 16 AML questions above in the thread, now you have been given the task to write a narrative, follow the following guidelines: "
                """ Begin the narrative with one of the following standalone statements, based on the findings:
                        The alert for this account is being closed as non-issue.
                        The alert for this account is being escalated for further review.
                    Structure the narrative as follows:
                        Cardholder Profile and Program Overview:
                            Start with an overview of the flagged account or card, including its purpose, specific limitations, and typical usage patterns for similar accounts or programs. Incorporate any available information about program-specific transaction thresholds and industry norms to establish an analytical baseline.
                        Credit and Debit Activity:
                            Summarize primary credits and debits, highlighting any significant spikes, geographic consistency, or unusual patterns. Focus on observed data, comparing the activity against expected norms for this program type, and identify adherence or deviations from thresholds.
                        Summary of Findings and Conclusion:
                            Present a clear summary that ties observed activity back to the opening decision. Highlight whether the activity aligns with expected use for the account or card program, referencing relevant investigative findings. Avoid speculative or interpretative statements, focusing strictly on data-supported conclusions.
                        Confidence Score:
                            Provide a confidence score indicating the level of certainty in the analysis, based on the thoroughness of the information and findings.
                        Conclude the narrative with one of the following standalone statements, reinforcing the decision:
                            Based on the findings, the alert is closed as non-issue.
                            Based on the findings, the alert is escalated for further review.

                    finally you have already answerd the 16 aml question, i will tell you the questions again that you already answered above in the thread.
                    Here are the key questions and answers:
                        What rule(s) did the alert generate for?
                        What is the Card/Account Program?
                        What is the Card/Account program description?
                        Does the CIP information verify in Lexis Nexis?
                        What is the primary cause(s) for the alerting activity?
                        What are other major credit(s) to the account?
                        What are other major debits(s) to the account?
                        What is the overall flow of funds through this account?
                        Did you find any negative news in Google or Lexis Nexis?
                        Is there anything relevant found in Google for profile of the cardholder?
                        Is activity occurring in/near Cardholder's residing area?
                        Is the expected activity showing a spike or fairly consistent?
                        Are there any additional red flags to address and can they be mitigated?
                        Should this alert be escalated or closed as non-issue?
                    Your goal is to present a professional, objective analysis that demonstrates the methodical and data-driven approach of an experienced FCRM analyst.
                """
            )
        )

        # Retrieve all messages in this run
    messages = list(client.beta.threads.messages.list(thread_id=thread.id, run_id=run.id))
    message_content = messages[0].content[0].text  # The assistant's response
    print(message_content.value)

    save_narrative_to_file(message_content.value)
    
def cli_main():
    parser = argparse.ArgumentParser(description="Run narrative analysis with provided files.")
    parser.add_argument("files", nargs="+", help="Paths to the files to be uploaded.")
    parser.add_argument(
        "--analysis", 
        dest="analysis_file",
        help="Path to the analysis file generated by the previous script (optional)."
    )
    args = parser.parse_args()

    execute_narrative_workflow(args.files, args.analysis_file)

if __name__ == "__main__":
    cli_main()
