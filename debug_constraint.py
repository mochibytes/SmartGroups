#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from constraint_parser import SchedulingConstraints
from scheduler import GroupScheduler
from csv_parser import parse_student_data

# Read the actual section1.csv data
with open('section1.csv', 'r') as f:
    lines = f.readlines()

# Parse CSV data
csv_data = []
for line in lines:
    csv_data.append(line.strip().split(','))

print("CSV Headers:", csv_data[0])
print("Number of students:", len(csv_data) - 1)

# Find the F column index
headers = csv_data[0]
f_index = None
for i, header in enumerate(headers):
    if header.strip().lower() == 'f':
        f_index = i
        break

if f_index is None:
    print("ERROR: Could not find 'F' column in CSV")
    sys.exit(1)

print(f"F column is at index {f_index}")

# Count F students
f_students = 0
for i in range(1, len(csv_data)):
    if csv_data[i][f_index].strip() == '1':
        f_students += 1

print(f"Total F students: {f_students}")

# Test with a subset of data first
test_data = csv_data[:6]  # First 5 students + header
print(f"\nTesting with {len(test_data)-1} students:")

# Parse the data
given_attributes = ['f']
result = parse_student_data(test_data, given_attributes)

if 'error' in result:
    print(f"Error parsing data: {result['error']}")
    sys.exit(1)

student_data = {
    'names': result['student_names'],
    'attributes': result['student_attributes'],
    'availabilities': result['student_availabilities']
}

print(f"\nParsed student data:")
for i, name in enumerate(student_data['names']):
    attrs = student_data['attributes'][i]
    f_val = attrs.get('f', '0')
    print(f"  {name}: F={f_val}")

# Create constraints: at least 1 F per group
constraints = SchedulingConstraints()
constraints.set_attribute_constraints({
    'f': {'min_per_group': 1}
})
constraints.set_group_size_constraints(2, 4)  # groups of 2-4 people
constraints.set_group_count_constraints(1, 3)  # 1-3 groups

print(f"\nConstraints: {constraints.get_attribute_constraints()}")

# Create scheduler and solve
scheduler = GroupScheduler(student_data, constraints)
solution = scheduler.schedule()

print(f"\nSolution:")
if 'error' in solution:
    print(f"Error: {solution['error']}")
else:
    for group in solution['groups']:
        print(f"Group {group['group_id']}: {[s['name'] for s in group['students']]}")
        f_count = sum(1 for s in group['students'] if s['attributes'].get('f', '0') == '1')
        print(f"  F (Female) count: {f_count}")
        if f_count < 1:
            print(f"  ❌ ERROR: Group {group['group_id']} has {f_count} F, but constraint requires at least 1!")
        else:
            print(f"  ✅ Group {group['group_id']} meets constraint")
