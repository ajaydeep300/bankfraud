from openai import OpenAI
import os
from dotenv import load_dotenv
import base64
import json
import snowflake.connector
import time
import re

def show_json(obj):
    print(json.dumps(json.loads(obj.model_dump_json()), indent=4))

# Load environment variables
load_dotenv()
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

conn = snowflake.connector.connect(
    account=os.getenv('SNOWFLAKE_ACCOUNT'),
    user=os.getenv('SNOWFLAKE_USER'),
    password=os.getenv('SNOWFLAKE_PASSWORD'),
    warehouse=os.getenv('SNOWFLAKE_WAREHOUSE'),
    database=os.getenv('SNOWFLAKE_DATABASE'),
    schema=os.getenv('SNOWFLAKE_SCHEMA')
)
cursor = conn.cursor()

def get_table_names(cursor):
    """Return a list of table names in the current schema."""
    query = "SHOW TABLES;"
    cursor.execute(query)
    table_names = [row[1] for row in cursor.fetchall()]  # The second column contains the table name
    return table_names

def get_column_names_and_types(cursor, table_name):
    """Return a list of column names and their data types for a given table."""
    query = f'DESCRIBE TABLE "{table_name}";'
    try:
        cursor.execute(query)
        columns = [(row[0], row[1]) for row in cursor.fetchall()]  # First column: name, second column: type
        return columns
    except snowflake.connector.errors.ProgrammingError as e:
        print(f"Error describing table {table_name}: {e}")
        return []

def get_database_info(cursor):
    """Return a list of dicts containing the table name, columns, and their data types."""
    table_dicts = []
    table_names = get_table_names(cursor)
    for table_name in table_names:
        print(f"Processing table: {table_name}")
        columns = get_column_names_and_types(cursor, table_name)
        column_names_with_types = [f"{col[0]} ({col[1]})" for col in columns]
        table_dicts.append({
            "table_name": table_name,
            "column_names": column_names_with_types
        })
    return table_dicts

# Fetch database schema
database_schema_dict = get_database_info(cursor)
database_schema_string = "\n".join(
    [
        f"Table: {table['table_name']}\nColumns: {', '.join(table['column_names'])}"
        for table in database_schema_dict
    ]
)

# Print the database schema
print(database_schema_string)

tools = [
    {
        "type": "function",
        "function": {
            "name": "ask_database",
            "description": "Use this function to answer user questions about transcations. Input should be a fully formed SQL query that can be run on snowflake db and compatible with column data type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": f"""
                                SQL query extracting info to answer the user's question.
                                SQL should be written using this database schema:
                                {database_schema_string}
                                The query should be returned in plain text, not in JSON.
                                """,
                    }
                },
                "required": ["query"],
            },
        }
    }
]

def ask_database(cursor, query):
    """Function to query Snowflake database with a provided SQL query."""
    try:
        cursor.execute(query)
        results = cursor.fetchall()
        if results:
            return results
        else:
            return "Query executed successfully but returned no results."
    except Exception as e:
        return f"Query failed with error: {e}"

def runAssistant(assistant_id, thread_id):
    run = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=assistant_id,
    )

    while True:
        run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)

        if run.status == "completed":
            print("This run has completed!")
            break
        else:
            print("in progress...")
            time.sleep(5)
    return run

def wait_on_run(run, thread):
    while run.status == "queued" or run.status == "in_progress":
        run = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id,
        )
        time.sleep(3)
    return run

ACC = ask_database(cursor,"select distinct acct_account_number from account_info")

narrative_questions = [
    {
        "section": "alert rules analysis",
        "question": "What rules are associated with the alert?",
        "sql_questions_to_analyze": [
        "List all rows in the TRANSACTIONS table where the PST_TXN_PROCESSOR_TRANSACTION_CODE equals 'PMTU' or the PST_TXN_PROCESSOR_TRANSACTION_CODE_DESCRIPTION contains 'Funds Transfer'. Sort the results by PST_TXN_TRANSACTION_DATE in descending order."
        ]
    },
    {
        "section": "alert rules analysis",
        "question": "What rules are associated with the alert?",
        "sql_questions_to_analyze": [
        "Find all rows in the TRANSACTIONS table where the PST_TXN_PROCESSOR_TRANSACTION_CODE equals 'PMC2' and the PST_TXN_PROCESSOR_TRANSACTION_CODE_DESCRIPTION contains 'Card to Card'. Sort the results by PST_TXN_TRANSACTION_DATE in descending order."
        ]
    },
    {
        "section": "card/account details",
        "question": "What is the program name and description for the card/account associated with PST_TXN_ACCOUNT_NUMBER?",
        "sql_questions_to_analyze": [
            f"""Find all rows in the ACCOUNT_INFO table where the ACCT_ACCOUNT_NUMBER = {ACC} matches the given PST_TXN_ACCOUNT_NUMBER. Retrieve the PRCSR_PROCESSOR_NAME and CARD_INTERNAL_CARD_STATUS_CODE for the account. Sort the results by CARD_CREATION_DATE in descending order."""
        ]
    },
    {
        "section": "card/account details",
        "question": "Which card or account is associated with the highest transaction amounts?",
        "sql_questions_to_analyze": [
            """Retrieve the following metrics for accounts and cards from the TRANSACTIONS table to determine the highest transaction amounts:
                  -Total Transaction Volume: The sum of CR and DB for each PST_TXN_ACCOUNT_NUMBER and PST_TXN_CARD_NUMBER.
                  -Largest Single Transaction: The maximum value of CR and DB for each PST_TXN_ACCOUNT_NUMBER and PST_TXN_CARD_NUMBER.
                  -Number of High-Value Transactions: The count of transactions where CR > 10 or DB > 300 for each PST_TXN_ACCOUNT_NUMBER and PST_TXN_CARD_NUMBER.
                  -Net Balance Change: The difference between SUM(CR) and SUM(DB) for each PST_TXN_ACCOUNT_NUMBER and PST_TXN_CARD_NUMBER."""
        ]
    },
    {
        "section": "transaction flow analysis",
        "question": "What are the top 10 largest credit (CR) transactions for the account number PST_TXN_ACCOUNT_NUMBER?",
        "sql_questions_to_analyze": [
            f"""Find the top 10 largest credit (CR) transactions for the specified PST_TXN_ACCOUNT_NUMBER = {ACC} from the TRANSACTIONS table. Retrieve the transaction date, card number, and credit amount, sorted in descending order of the credit amount."""
        ]
    },
    {
        "section": "transaction flow analysis",
        "question": "What are the top 10 largest debit (DB) transactions for the account number PST_TXN_ACCOUNT_NUMBER?",
        "sql_questions_to_analyze": [
            f"""Find the top 10 largest debit (DB) transactions for the specified PST_TXN_ACCOUNT_NUMBER = {ACC} from the TRANSACTIONS table. Retrieve the transaction date, card number, and debit amount, sorted in descending order of the debit amount."""
        ]
    },
    {
        "section": "transaction flow analysis",
        "question": "Calculate the total inflow (CR), total outflow (DB), and net balance change for account number PST_TXN_ACCOUNT_NUMBER over the past 90 days.",
        "sql_questions_to_analyze": [
            f"""Calculate the total inflow (SUM(CR)), total outflow (SUM(DB)), and net balance change (SUM(CR) - SUM(DB)) for the specified PST_TXN_ACCOUNT_NUMBER = {ACC} from the TRANSACTIONS table over the past 90 days."""
        ]
    },
    {
        "section": "anomaly and red flag detection",
        "question": "List all transactions where the debit (DB) or credit (CR) amount exceeds $500.",
        "sql_questions_to_analyze": [
            "Find all rows in the TRANSACTIONS table where CR > 500 or DB > 500. Sort the results by PST_TXN_TRANSACTION_DATE in descending order."
        ]
    },
    {
        "section": "anomaly and red flag detection",
        "question": "Identify duplicate transactions where all attributes are the same, including PST_TXN_ACCOUNT_NUMBER, CR, DB, and PST_TXN_TRANSACTION_DATE.",
        "sql_questions_to_analyze": [
            "Identify duplicate transactions in the TRANSACTIONS table where all attributes, including PST_TXN_ACCOUNT_NUMBER, CR, DB, and PST_TXN_TRANSACTION_DATE, are the same. Return the duplicated rows along with the count of occurrences for each duplicate."
        ]
    },
    {
        "section": "behavioral analysis",
        "question": "Show a time series of transaction counts and amounts for the account number PST_TXN_ACCOUNT_NUMBER to detect spikes or anomalies.",
        "sql_questions_to_analyze": [
            f"""Generate a time series showing the daily count of transactions and the total transaction amount (CR + DB) for the specified PST_TXN_ACCOUNT_NUMBER = {ACC}. Sort the results by transaction date in ascending order to detect spikes or anomalies."""
        ]
    },
    {
        "section": "behavioral insights",
        "question": "Which dormant accounts (no transactions for the past 3 months recently showed large transactions?",
        "sql_questions_to_analyze": [
            "Identify card numbers from the TRANSACTIONS table that had no transactions in the past 3 months but recently showed large transactions (CR > 100 or DB > 500). Include the account number,card number, transaction date, transaction amount, and type (credit or debit). Limit the results to the most recent large transactions."
        ]
    },
    {
        "section": "pattern detetction",
        "question": "High frequency of large-dollar transactions within a short time frame.",
        "sql_questions_to_analyze": [
            "Identify accounts or cards from the TRANSACTIONS table that have more than 3 transactions with CR > 50 or DB > 500 within a 15-day period. Return the account number and card number, the total count of such transactions, and the time frame during which they occurred."
        ]
    },
    {
        "section": "pattern detetction",
        "question": "Multiple transactions to the same account or card number, suggesting funneling of funds.",
        "sql_questions_to_analyze": [
            "Identify accounts or cards from the TRANSACTIONS table that have more than 5 transactions to the same PST_TXN_ACCOUNT_NUMBER or PST_TXN_CARD_NUMBER within a single day. Return the account number or card number, the count of such transactions, and the transaction date."
        ]
    },
    {
        "section": "pattern detetction",
        "question": "Frequent 'Card to Card Transfer' or 'Account to Account Transfer' transactions lacking a clear purpose.",
        "sql_questions_to_analyze": [
            "Identify accounts or cards from the TRANSACTIONS table with more than 3 transactions labeled as 'Card to Card Transfer' or 'Account to Account Transfer' within a single week. Return the account number or card number, the count of such transactions, and the transaction date range."
        ]
    },
    {
        "section": "pattern detetction",
        "question": "Transactions flagged with codes related to lost or stolen cards being processed repeatedly.",
        "sql_questions_to_analyze": [
            "Identify transactions from the TRANSACTIONS table where the associated card is flagged as lost or stolen (CARD_PROCESSOR_CARD_STATUS_CODE = 'L'), and more than 2 transactions have been processed after the card was reported lost or stolen within a 30-day window. Return the card number, the account number, the count of such transactions, and the date range of these transactions."
        ]
    },
    {
        "section": "pattern detetction",
        "question": "Unusual sequence of credits immediately followed by similar debits, indicating rapid fund movement.",
        "sql_questions_to_analyze": [
            f"""Identify transactions from the TRANSACTIONS table where a credit (CR) is immediately followed by a debit (DB) of a similar amount (±10%) on the account (PST_TXN_ACCOUNT_NUMBER = {ACC} within a 1-day window. Return the account number, transaction date, credit amount, debit amount, and the time difference between the two transactions."""
        ]
    },
    {
        "section": "pattern detetction",
        "question": "Significant increases in transaction amounts that are not in line with historical spending patterns.",
        "sql_questions_to_analyze": [
            "Identify accounts from the TRANSACTIONS table where the average transaction amount (CR + DB) in the last 30 days is more than double the average transaction amount over the prior 6 months. Return the account number, the average transaction amount for the last 30 days, the average transaction amount for the prior 3 months, and the percentage increase."
        ]
    },
    {
        "section": "pattern detetction",
        "question": "Multiple transactions involving zero or minimal MCC code details, obscuring the merchant’s identity.",
        "sql_questions_to_analyze": [
            "Identify accounts or cards from the TRANSACTIONS table that have more than 3 transactions where the PST_TXN_MCC_CODE = 0 or the PST_TXN_MCC_CATEGORY_1_DESCRIPTION is null within a single month. Return the account number, card number, the count of such transactions, and the transaction date range."
        ]
    },
    {
        "section": "identity verification",
        "question": "Patterns of use involving multiple card numbers or account numbers linked to the same SSN or masked identifiers.",
        "sql_questions_to_analyze": [
            "Identify cases where multiple card numbers or account numbers in the ACCOUNT_INFO table are linked to the same SSN from the FRAUD_DATA table. Return the SSN, the count of unique accounts and cards, and the list of associated account numbers and card numbers."
        ]
    }
]

to = [
    {
        "type": "function",
        "function": {
            "name": "ask_database",
            "description": "Use this function to answer user questions about transcations. Input should be a fully formed SQL query...",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": f"""
                                SQL query extracting info to answer the user's question.
                                SQL should be written using this database schema:
                                {database_schema_string}
                                """,
                    }
                },
                "required": ["query"],
            },
        }
    }
]

thread = client.beta.threads.create()
assistantAnalyst = client.beta.assistants.create(
    name="Analyst",
    instructions=(
        f"You are a financial statement analyst. Your role is to interpret..."
        f"strictly adhering to the database structure: {database_schema_string}"
    ),
    model="gpt-4o",
    tools=[tools[0]]  # first tool from tools array
)

###################################################
# WRAP THE FINAL LOOP + FILE WRITING INTO MAIN()
###################################################
def main():
    """
    This function runs the entire analysis from start to finish.
    It writes all results to 'files/responses_log.txt'.
    Once complete, it closes the Snowflake cursor and connection.
    """
    
    with open("files/responses_log.txt", "w") as log_file:

        for ques in narrative_questions:
            section = ques["section"]
            question = ques["question"]
            sql_question = ques["sql_questions_to_analyze"]

            messages = [{
                "role": "user",
                "content": f'answer the following question: {sql_question}'
            }]

            response = client.chat.completions.create(
                model='gpt-4o',
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )

            response_message = response.choices[0].message
            messages.append(response_message)

            print(response_message)  # debugging

            tool_calls = response_message.tool_calls
            if tool_calls:
                tool_call_id = tool_calls[0].id
                tool_function_name = tool_calls[0].function.name
                tool_query_string = json.loads(tool_calls[0].function.arguments)['query']

                if tool_function_name == 'ask_database':
                    results = ask_database(cursor, tool_query_string)
                    if isinstance(results, list):
                        results_string = "\n".join([", ".join(map(str, row)) for row in results])
                    else:
                        results_string = str(results)

                    print("Results from ask_database:\n", results_string)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_function_name,
                        "content": (
                            "summarize the following result from the database in a way "
                            "that your response mentions all the details and does not "
                            "utilize the words etc, similar results : "
                            f"{results_string}"
                        )
                    })

                    model_response_with_function_call = client.chat.completions.create(
                        model="gpt-4o",
                        messages=messages,
                    )
                    final_response = model_response_with_function_call.choices[0].message.content
                    print(final_response)

                    log_file.write(f"Section: {section}\n")
                    log_file.write(f"Question: {question}\n")
                    log_file.write(f"SQL Question: {sql_question}\n")
                    log_file.write(f"Model Response: {final_response}\n")
                    log_file.write("\n" + "="*50 + "\n\n")

                else:
                    print(f"Error: function {tool_function_name} does not exist")
                    log_file.write(f"Section: {section}\n")
                    log_file.write(f"Question: {question}\n")
                    log_file.write(f"SQL Question: {sql_question}\n")
                    log_file.write(f"Model Response: Error: function {tool_function_name} does not exist\n")
                    log_file.write("\n" + "="*50 + "\n\n")

            else:
                # No tool calls made
                print(response_message.content)
                log_file.write(f"Section: {section}\n")
                log_file.write(f"Question: {question}\n")
                log_file.write(f"SQL Question: {sql_question}\n")
                log_file.write(f"Model Response: {response_message.content}\n")
                log_file.write("\n" + "="*50 + "\n\n")

    # Once done, close Snowflake resources
    cursor.close()
    conn.close()
    print("Analysis complete. responses_log.txt written, Snowflake connection closed.")

# ---------------------------
# If run from CLI, do everything.
# ---------------------------
if __name__ == "__main__":
    main()
