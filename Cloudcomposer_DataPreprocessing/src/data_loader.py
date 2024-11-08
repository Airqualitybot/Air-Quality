import pandas as pd
import os
import logging
from google.cloud import storage
import io

# Configure logging for anomaly detection
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CSVStacker:
    def __init__(self, bucket_name, folder_path):
        self.bucket_name = bucket_name
        self.folder_path = folder_path
        self.dataframes = []
        self.stacked_df = None
        self.storage_client = storage.Client()

    def load_csv_files(self):
        try:
            blobs = self.storage_client.list_blobs(self.bucket_name, prefix=self.folder_path)
            csv_files = [blob.name for blob in blobs if blob.name.endswith('.csv')]
            if not csv_files:
                logger.warning(f"No CSV files found in '{self.folder_path}'.")
                return ["No CSV files found"]

            anomalies = []
            for file_name in csv_files:
                blob = self.storage_client.bucket(self.bucket_name).blob(file_name)
                file_size = blob.size
                if file_size == 0:
                    anomaly = f"File '{file_name}' is empty and was skipped."
                    logger.warning(anomaly)
                    anomalies.append(anomaly)
                    continue

                # Read CSV directly from GCS
                df = pd.read_csv(blob.open("rb"))
                self.dataframes.append(df)
                logger.info(f"Loaded file '{file_name}' successfully.")

            if not self.dataframes:
                anomalies.append("No valid data files were loaded.")
                logger.error("No valid data files were loaded.")
            return anomalies
        except Exception as e:
            logger.error(f"Error loading CSV files: {e}")
            return [str(e)]

    def detect_column_consistency(self):
        if not self.dataframes:
            logger.error("No DataFrames loaded to check for column consistency.")
            return ["No DataFrames loaded to check for column consistency"]

        anomalies = []
        first_columns = self.dataframes[0].columns
        for i, df in enumerate(self.dataframes[1:], start=1):
            if not df.columns.equals(first_columns):
                anomaly = f"Column mismatch detected in DataFrame {i}."
                logger.error(anomaly)
                anomalies.append(anomaly)
        if not anomalies:
            logger.info("All columns are consistent.")
        return anomalies

    def detect_data_anomalies(self):
        anomalies = []
        for i, df in enumerate(self.dataframes):
            for column in ["date", "parameter", "value"]:
                if column not in df.columns:
                    anomaly = f"Missing critical column '{column}' in DataFrame {i}."
                    logger.error(anomaly)
                    anomalies.append(anomaly)

            for _, row in df.iterrows():
                if row["parameter"] in ["pm25", "pm10", "o3", "no2", "so2", "co"] and row["value"] < 0:
                    anomaly = f"Invalid negative value detected for {row['parameter']}: {row['value']} on {row['date']} in DataFrame {i}."
                    logger.warning(anomaly)
                    anomalies.append(anomaly)
        return anomalies

    def stack_dataframes(self):
        if not self.dataframes:
            logger.error("No DataFrames to stack. Please load CSV files first.")
            return ["No DataFrames to stack"]
        
        self.stacked_df = pd.concat(self.dataframes, ignore_index=True)
        logger.info("DataFrames stacked successfully.")
        return []

    def save_as_pickle(self, output_path):
        if self.stacked_df is None:
            anomaly = "No DataFrame to save. Please stack the dataframes first."
            logger.error(anomaly)
            return [anomaly]
        
        # Save to GCS as a pickle file
        pickle_buffer = io.BytesIO()
        self.stacked_df.to_pickle(pickle_buffer)
        pickle_buffer.seek(0)
        blob = self.storage_client.bucket(self.bucket_name).blob(output_path)
        blob.upload_from_file(pickle_buffer, content_type='application/octet-stream')
        logger.info(f"Stacked DataFrame saved as '{output_path}'.")
        return []

def stack_csvs_to_pickle(bucket_name, folder_path, output_pickle_file):
    csv_stacker = CSVStacker(bucket_name, folder_path)
    anomalies = []

    # Step 1: Load files and detect file-level anomalies
    anomalies.extend(csv_stacker.load_csv_files())

    # Step 2: Detect column consistency anomalies
    anomalies.extend(csv_stacker.detect_column_consistency())

    # Step 3: Detect data-related anomalies
    anomalies.extend(csv_stacker.detect_data_anomalies())

    # If no anomalies are detected, proceed with stacking and saving
    if not anomalies:
        anomalies.extend(csv_stacker.stack_dataframes())
        anomalies.extend(csv_stacker.save_as_pickle(output_pickle_file))
        logger.info("No anomalies detected. Process completed successfully.")
    else:
        logger.error("Anomalies detected; skipping stacking and saving.")

    return anomalies  # Return list of all detected anomalies

if __name__ == "__main__":
    bucket_name = "your-bucket-name"  # Replace with your GCS bucket name
    folder_path = "dags/DataPreprocessing/src/data_store_pkl_files/csv"
    output_pickle_file = "dags/DataPreprocessing/src/data_store_pkl_files/air_pollution.pkl"

    detected_anomalies = stack_csvs_to_pickle(bucket_name, folder_path, output_pickle_file)
    if detected_anomalies:
        logger.error(f"Detected Anomalies: {detected_anomalies}")
    else:
        logger.info("No anomalies detected. Process completed successfully.")
