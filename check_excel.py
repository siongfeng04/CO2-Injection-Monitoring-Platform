import pandas as pd

df = pd.read_excel('data/excel/combined_co2_data_only_file.xls', sheet_name='Dataset_Test')
df['Date & Time'] = pd.to_datetime(df['Date & Time'])

# Check if target timestamp exists
target = pd.to_datetime('2009-09-25 07:42:45')
match = df[df['Date & Time'] == target]

print('Found exact match:', len(match) > 0)
if len(match) > 0:
    print('\nData at target timestamp:')
    print(match.iloc[0])
else:
    print('\nClosest data points:')
    print(df.tail(5))
    print('\nDate range:', df['Date & Time'].min(), 'to', df['Date & Time'].max())
