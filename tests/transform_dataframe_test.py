import pandas as pd
import re, time
import numpy as np


def transform_dataframe(df):
    # Extract columns
    new_rows = []
    current_time = int(time.time())
    for col in df.columns:
        match = re.match(r"([^:]+)\.([^:]+)(?::(\d+))?(?:_(\d+))?$", col)
        #match = re.match(r"([^:]+):([^:]+)(?::(\d+))?", col)
        if match:
            tagname, worker_name, timestamp, dim = match.groups()
            print(tagname,worker_name,timestamp,dim)
            #print(df[col])
            #new_rows.append([tagname, worker_name, int(timestamp) if timestamp else current_time, pd.Series(df[col].values)])
            for index, value in df[col].items():
               new_rows.append([f"{tagname}_{index}", worker_name, int(timestamp) if timestamp else current_time, value])

    # Create new dataframe
    new_df = pd.DataFrame(new_rows, columns=['tag', 'worker', 'timestamp', 'value'])
    return new_df

"""
<class 'pandas.core.frame.DataFrame'>
RangeIndex: 10 entries, 0 to 9
Data columns (total 7 columns):
 #   Column                    Non-Null Count  Dtype 
---  ------                    --------------  ----- 
 0   Throughput.worker2        10 non-null     int64 
 1   Throughput.worker1        10 non-null     int64 
 2   Throughput.10.227.86.172  0 non-null      object
 3   Throughput.worker3        0 non-null      object
 4   RollSpeed.worker1         10 non-null     int64 
 5   RollSpeed.worker2         10 non-null     int64 
 6   RollSpeed.10.227.86.172   0 non-null      object


"""

# Example usage
data = {
    'SurfacePressure.workerA:1739906619': pd.Series(np.array([1.2, 1.3])),
    'sensor2:workerB': pd.Series(np.array([2.4, 2.5])),
    'sensor3:workerC:1708371300': pd.Series([3.5, 3.6]),
    'sensor4:workerD':pd.Series([4.5, 4.6])
}
df = pd.DataFrame(data)
print(df.info(verbose=True))
transformed_df = transform_dataframe(df)
print(transformed_df.info(verbose=True))
print(transformed_df.head)