from airflow import DAG
import os
import sys
from airflow import configuration as conf
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.operators.email import EmailOperator
from airflow.operators.dummy import DummyOperator
from datetime import timedelta,datetime
from airflow.utils.dates import days_ago
from dags.DataPreprocessing.src.data_air import download_data_function
from dags.DataPreprocessing.src.data_loader import stack_csvs_to_pickle
from dags.DataPreprocessing.src.data_split import split
from dags.DataPreprocessing.src.train.data_preprocessing.pivoting_data import pivot_parameters as pivoting_data_train
from dags.DataPreprocessing.src.train.data_preprocessing.removal_of_uneccesary_cols import remove_uneccesary_cols as removal_of_uneccesary_cols_train
from dags.DataPreprocessing.src.train.data_preprocessing.anamoly_detection import anamoly_detection_val as anamoly_detection_train
from dags.DataPreprocessing.src.train.data_preprocessing.check_missing_values import handle_missing_vals as check_missing_values_train
from dags.DataPreprocessing.src.train.data_preprocessing.feature_eng import feature_engineering as feature_eng_train
from dags.DataPreprocessing.src.test.data_preprocessing.pivoting_data import pivot_parameters as pivoting_data_test
from dags.DataPreprocessing.src.test.data_preprocessing.removal_of_uneccesary_cols import remove_uneccesary_cols as removal_of_uneccesary_cols_test
from dags.DataPreprocessing.src.test.data_preprocessing.anamoly_detection import anamoly_detection_val as anamoly_detection_test
from dags.DataPreprocessing.src.test.data_preprocessing.check_missing_values import handle_missing_vals as check_missing_values_test
from dags.DataPreprocessing.src.test.data_preprocessing.feature_eng import feature_engineering as feature_eng_test
from dags.DataPreprocessing.src.Schema.check_schema_original_airpollution import  main_generate_schema_and_statistics as main_check_schema_original
from dags.DataPreprocessing.src.Schema.test_schema.check_output_data_schema import main_generate_schema_and_statistics as main_test_schema
from dags.DataPreprocessing.src.Schema.train_schema.check_output_data_schema import main_generate_schema_and_statistics as main_train_schema

conf.set('core', 'enable_xcom_pickling', 'True')
conf.set('core', 'enable_parquet_xcom', 'True')

def check_anomalies_and_send_email(**kwargs):
    anomalies = kwargs['ti'].xcom_pull(task_ids='download_data_from_api')
    logging.info(f"Anomalies detected: {anomalies}")
    if anomalies:  # If anomalies are detected, trigger the email
        logging.info("Branching to send_anomaly_alert_api")
        return 'send_anomaly_alert_api'
    logging.info("Branching to continue_pipeline")
    return 'continue_pipeline'

def check_anomalies_loading_data(**kwargs):
    anomalies = kwargs['ti'].xcom_pull(task_ids='load_data_pickle')
    logging.info(f"Anomalies detected: {anomalies}")
    if anomalies:  # If anomalies are detected, trigger the email
        logging.info("send_anomaly_alert_load_data")
        return 'send_anomaly_alert_load_data'
    logging.info("Branching to continue_pipeline")
    return 'continue_pipeline_load_data'


default_args = {
    'owner': 'MLOPS',
    'start_date': datetime(2024, 10, 21),
    'retries': 1, # Number of retries in case of task failure
    'retry_delay': timedelta(minutes=1), # Delay before retries
}

dag = DAG(
    'datapipeline_new',
    default_args=default_args,
    description='Data Preprocessing pipeline using Airflow DAG',
    schedule_interval=None,
    catchup=False
)

# download the data in form of csv using data api 
download_data_api = PythonOperator(
    task_id='download_data_from_api',
    python_callable=download_data_function,
    dag=dag
)

branch_task = BranchPythonOperator(
    task_id='check_anomalies_and_send_email',
    python_callable=check_anomalies_and_send_email,
    provide_context=True,
    dag=dag
)

branch_task_load_data = BranchPythonOperator(
    task_id='check_anomalies_loading_data',
    python_callable=check_anomalies_loading_data,
    provide_context=True,
    dag=dag
)

send_anomaly_alert = EmailOperator(
    task_id='send_anomaly_alert_api',
    to='followsrilu345@gmail.com',
    subject='Data Anomaly Alert for API',
    html_content="""<p>Anomalies detected in the data pipeline while using API. Details:</p>
                    {% set anomalies = ti.xcom_pull(task_ids='download_data_from_api') %}
                    {% if anomalies %}
                        {% if anomalies is string %}
                            <ul><li>{{ anomalies }}</li></ul>
                        {% else %}
                            <ul>{% for item in anomalies %}<li>{{ item }}</li>{% endfor %}</ul>
                        {% endif %}
                    {% else %}
                        <p>No specific anomaly details available.</p>
                    {% endif %}""",
    dag=dag
)

send_anomaly_alert_load_data = EmailOperator(
    task_id='send_anomaly_alert_load_data',
    to='followsrilu345@gmail.com',
    subject='Data Anomaly Alert for Loading Data',
    html_content="""<p>Anomalies detected in the data pipeline while loading data. Details:</p>
                    {% set anomalies = ti.xcom_pull(task_ids='load_data_pickle') %}
                    {% if anomalies %}
                        <ul>{% for item in anomalies %}<li>{{ item }}</li>{% endfor %}</ul>
                    {% else %}
                        <p>No specific anomaly details available.</p>
                    {% endif %}""",
    dag=dag
)

continue_pipeline = DummyOperator(task_id='continue_pipeline', dag=dag)

continue_pipeline_load_data = DummyOperator(task_id='continue_pipeline_load_data', dag=dag)

merge_branch = DummyOperator(task_id='merge_branch', trigger_rule='none_failed_min_one_success',dag=dag)

merge_branch_load_data = DummyOperator(task_id='merge_branch_load_data', trigger_rule='none_failed_min_one_success',dag=dag)

# load the data and save it in pickle file
data_Loader = PythonOperator(
    task_id='load_data_pickle',
    python_callable=stack_csvs_to_pickle,
    dag=dag
)

# split data into traning and testing
data_Split = PythonOperator(
    task_id='split_train_test',
    python_callable=split,
    dag=dag
)

data_schema_original = PythonOperator(
    task_id = 'check_schema_of_original_air_data',
    python_callable = main_check_schema_original,
    dag = dag
)

# pivot the data to contain pm2.5 parameters for train data
data_train_pivot = PythonOperator(
    task_id='pivot_data_train',
    python_callable=pivoting_data_train,
    dag=dag
)

# pivot the data to contain pm2.5 parameters for test data
data_test_pivot = PythonOperator(
    task_id='pivot_data_test',
    python_callable=pivoting_data_test,
    dag=dag
)

# remove values regarding other gases train data
data_remove_cols_train = PythonOperator(
    task_id='data_remove_cols_train',
    python_callable=removal_of_uneccesary_cols_train,
    dag=dag
)

# remove values regarding other gases test data
data_remove_cols_test = PythonOperator(
    task_id='data_remove_cols_test',
    python_callable=removal_of_uneccesary_cols_test,
    dag=dag
)

# handle missing values train data
handle_missing_vals_train = PythonOperator(
    task_id='handle_missing_vals_train',
    python_callable=check_missing_values_train,
    dag=dag
)

# handle missing values test data
handle_missing_vals_test = PythonOperator(
    task_id='handle_missing_vals_test',
    python_callable=check_missing_values_test,
    dag=dag
)

# handle anamolies for train data
anamolies_vals_train = PythonOperator(
    task_id='anamolies_vals_train',
    python_callable=anamoly_detection_train,
    dag=dag
)

#handle anamolies for test data
anamolies_vals_test = PythonOperator(
    task_id='anamolies_vals_test',
    python_callable=anamoly_detection_test,
    dag=dag
)

# feature engineering for train data
feature_engineering_train = PythonOperator(
    task_id='feature_engineering_train',
    python_callable=feature_eng_train,
    dag=dag
)

data_schema_train_data_feature_eng = PythonOperator(
    task_id = 'schema_train_data_final_processed',
    python_callable = main_train_schema,
    dag = dag
)

data_schema_test_data_feature_eng = PythonOperator(
    task_id = 'schema_test_data_final_processed',
    python_callable = main_test_schema,
    dag = dag
)

# feature engineering for test data
feature_engineering_test = PythonOperator(
    task_id='feature_engineering_test',
    python_callable=feature_eng_test,
    dag=dag
)

# order in which tasks are run
download_data_api >> branch_task >> [send_anomaly_alert, continue_pipeline] >> merge_branch \
>> data_Loader >> branch_task_load_data >> [send_anomaly_alert_load_data,continue_pipeline_load_data] >> merge_branch_load_data \
>> data_Split >> data_schema_original \
>> data_train_pivot >> data_remove_cols_train >> handle_missing_vals_train \
>> anamolies_vals_train >> feature_engineering_train >> data_test_pivot >> data_remove_cols_test >> handle_missing_vals_test \
>> anamolies_vals_test >> feature_engineering_test >> data_schema_train_data_feature_eng >> data_schema_test_data_feature_eng

if __name__ == "__main__":
    dag.cli()

