import pandas as pd
import re
from snowflake.connector import connect
from dotenv import load_dotenv
import os

load_dotenv()
# Snowflake credentials
SNOWFLAKE_ACCOUNT = os.getenv('SNOWFLAKE_ACCOUNT')
SNOWFLAKE_USER = os.getenv('SNOWFLAKE_USER')
SNOWFLAKE_PASSWORD = os.getenv('SNOWFLAKE_PASSWORD')
SNOWFLAKE_DATABASE = os.getenv('SNOWFLAKE_DATABASE')
SNOWFLAKE_SCHEMA = os.getenv('SNOWFLAKE_SCHEMA')
SNOWFLAKE_WAREHOUSE =os.getenv('SNOWFLAKE_WAREHOUSE')

file_paths = [
    '/Users/ajaydeepsingh/JupyterProjects/frauddetect/files/account_info.xlsx',
    '/Users/ajaydeepsingh/JupyterProjects/frauddetect/files/fraud.xlsx',
    '/Users/ajaydeepsingh/JupyterProjects/frauddetect/files/transactions.xlsx'
]

fraud_data_schema = {
    "FIRST_NAME": "VARCHAR",
    "LAST_NAME": "VARCHAR",
    "SSN": "VARCHAR",
    "CARD_NUMBER": "VARCHAR",
    "ALT_CARD_NUMBER": "VARCHAR",
    "ACCOUNT_NUMBER": "VARCHAR",
    "BALANCE": "DECIMAL(18,2)",
    "PROCESSOR_STATUS": "VARCHAR",
    "ADDRESS_LINE_1": "VARCHAR",
    "ADDRESS_LINE_2": "VARCHAR",
    "CITY": "VARCHAR",
    "STATE": "VARCHAR(2)",
    "ZIP": "VARCHAR(10)",
    "PHONE": "VARCHAR",
    "PROGRAM_ID": "VARCHAR",
    "PROCESSOR_NAME": "VARCHAR",
    "DATE_OF_BIRTH": "DATE"
}

account_info_schema = {
    "ACCT_ACCOUNT_NUMBER": "VARCHAR",
    "CARD_CARD_NUMBER": "VARCHAR",
    "CARD_PSEUDO_NUMBER": "VARCHAR",
    "CARD_FIRST_OR_FULL_NAME": "VARCHAR",
    "CARD_LAST_NAME": "VARCHAR",
    "CARD_CUSTOMER_DOB": "DATE",
    "CARD_EMAIL_ADDRESS": "VARCHAR",
    "CARD_SOCIAL_SECURITY_NUMBER": "VARCHAR",
    "CARD_PROCESSOR_CURRENT_SETTLED_BALANCE": "DECIMAL(18,2)",
    "ACCT_AVAILABLE_BALANCE": "DECIMAL(18,2)",
    "CARD_INTERNAL_CARD_STATUS_CODE": "VARCHAR",
    "CARD_PROCESSOR_CARD_STATUS_CODE": "VARCHAR",
    "ACCT_OPEN_DATE": "DATE",
    "CARD_CREATION_DATE": "DATE",
    "CARD_POC_PROCESS_DATE": "DATE",
    "CARD_POC_WORK_OF_DATE": "DATE",
    "CARD_PSTL_ADDRESS_1_LINE": "VARCHAR",
    "CARD_PSTL_ADDRESS_2_LINE": "VARCHAR",
    "CARD_PSTL_CITY_NAME": "VARCHAR",
    "CARD_PSTL_STATE_CODE": "VARCHAR(2)",
    "CARD_PSTL_POSTAL_CODE": "VARCHAR(10)",
    "PHONE_NUMBER": "VARCHAR",
    "PHONE_NUMBER_ROLE_TYPE": "VARCHAR",
    "PRCSR_PROCESSOR_NAME": "VARCHAR"
}

transactions_schema = {
    "PRCSR_PROCESSOR_NAME": "VARCHAR",
    "PST_TXN_ACCOUNT_NUMBER": "VARCHAR",
    "PST_TXN_CARD_NUMBER": "VARCHAR",
    "PST_TXN_TRANSACTION_DATE": "DATE",
    "PST_TXN_PROCESSOR_TRANSACTION_CODE": "VARCHAR",
    "PST_TXN_PROCESSOR_TRANSACTION_CODE_DESCRIPTION": "VARCHAR",
    "PST_TXN_INTERNAL_TRANSACTION_CODE": "VARCHAR",
    "PST_TXN_INTERNAL_TRANSACTION_SUB_CODE": "VARCHAR",
    "PST_TXN_MCC_CODE": "INT",
    "PST_TXN_MCC_CATEGORY_1_DESCRIPTION": "VARCHAR",
    "PST_TXN_MCC_CATEGORY_2_DESCRIPTION": "VARCHAR",
    "PST_TXN_TRANSACTION_DESCRIPTION_DETAIL": "VARCHAR",
    "CR": "DECIMAL(18,2)",
    "DB": "DECIMAL(18,2)"
}

table_schemas = {
    "FRAUD_DATA": fraud_data_schema,
    "ACCOUNT_INFO": account_info_schema,
    "TRANSACTIONS": transactions_schema
}

fraud_data_expected_columns = list(fraud_data_schema.keys())
account_info_expected_columns = list(account_info_schema.keys())
transactions_expected_columns = list(transactions_schema.keys())

def identify_table_name_and_expected_columns(file_path):
    fname = file_path.split('/')[-1].split('.')[0].upper()
    if "FRAUD" in fname:
        return "FRAUD_DATA", fraud_data_expected_columns
    elif "ACCOUNT_INFO" in fname:
        return "ACCOUNT_INFO", account_info_expected_columns
    elif "TRANSACTION" in fname:
        return "TRANSACTIONS", transactions_expected_columns
    else:
        return fname, []

def normalize_column_name(name):
    name = re.sub(r'[^A-Za-z0-9_]', '', name.replace(' ', '_')).upper()
    if not name:
        name = "UNKNOWN_COLUMN"
    if name[0].isdigit():
        name = f"COLUMN_{name}"
    return name

def find_header_row(df, expected_columns):
    normalized_expected = [normalize_column_name(col) for col in expected_columns]
    best_row = None
    best_score = -1
    rows_to_check = min(50, df.shape[0])
    for i in range(rows_to_check):
        row_values = df.iloc[i].astype(str).str.strip()
        normalized_cells = [normalize_column_name(val) for val in row_values]
        score = sum(1 for val in normalized_cells if val in normalized_expected)
        if score > best_score:
            best_score = score
            best_row = i
    return best_row

def sanitize_column_name(col, existing_columns):
    col = normalize_column_name(col)
    original_col = col
    counter = 1
    while col in existing_columns:
        col = f"{original_col}_{counter}"
        counter += 1
    existing_columns.add(col)
    return col

def process_and_upload_file(file_path):
    table_name, expected_columns = identify_table_name_and_expected_columns(file_path)
    df = pd.read_excel(file_path, header=None)

    if expected_columns:
        header_row = find_header_row(df, expected_columns)
        if header_row is not None:
            new_header = df.iloc[header_row].astype(str).str.strip()
            df = df.iloc[header_row+1:]
            df.columns = new_header
        else:
            df.columns = [f"COLUMN_{i}" for i in range(df.shape[1])]
    else:
        df.columns = [f"COLUMN_{i}" for i in range(df.shape[1])]

    existing_columns = set()
    df.columns = [sanitize_column_name(col, existing_columns) for col in df.columns]

    selected_schema = table_schemas.get(table_name, {})

    conn = connect(
        user=SNOWFLAKE_USER,
        password=SNOWFLAKE_PASSWORD,
        account=SNOWFLAKE_ACCOUNT
    )
    cursor = conn.cursor()

    cursor.execute(f"USE DATABASE {SNOWFLAKE_DATABASE}")
    cursor.execute(f"USE SCHEMA {SNOWFLAKE_SCHEMA}")
    cursor.execute(f"USE WAREHOUSE {SNOWFLAKE_WAREHOUSE}")

    column_definitions = []
    for col in df.columns:
        col_type = selected_schema.get(col, "VARCHAR")
        column_definitions.append(f'"{col}" {col_type}')

    create_table_sql = f"CREATE OR REPLACE TABLE {table_name} ({', '.join(column_definitions)})"
    cursor.execute(create_table_sql)

    df = df.where(pd.notnull(df), None)
    for _, row in df.iterrows():
        values = []
        for val, col in zip(row, df.columns):
            if val is None:
                values.append("NULL")
            else:
                if isinstance(val, str):
                    val = val.strip()
                col_type = selected_schema.get(col, "VARCHAR")
                if "DATE" in col_type.upper() and isinstance(val, pd.Timestamp):
                    val = val.strftime("%Y-%m-%d")
                escaped_val = str(val).replace("'", "''")
                values.append(f"'{escaped_val}'")
        insert_sql = f"INSERT INTO {table_name} VALUES ({', '.join(values)})"
        cursor.execute(insert_sql)

    print(f"Data from {file_path} uploaded to {table_name} successfully.")
    cursor.close()
    conn.close()

############################
# ADDED: DYNAMIC OVERRIDE
############################
def set_file_paths(paths):
    """
    Overwrites the global 'file_paths' with the new files saved locally.
    """
    global file_paths
    file_paths = paths

def main():
    """
    Retains the exact logic of processing each file in 'file_paths'.
    """
    for fp in file_paths:
        process_and_upload_file(fp)

# No changes below this line, so that code remains identical.
# If you want to run from CLI, it still defaults to the original file_paths above.
if __name__ == "__main__":
    main()
