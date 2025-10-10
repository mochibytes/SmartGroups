import io
import csv
import pandas as pd
from constraint_parser import SchedulingConstraints
import json

def get_csv(request):
    if 'file' not in request.files:
        return {'error': 'No file part', 'status': 400}

    file = request.files['file'] # get the file user uploads

    if file.filename == '':
        return {'error': 'No selected file', 'status': 400}
    
    stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
    csv_input = list(csv.reader(stream)) # csv_input is a list of lists, each inner list is a row
    
    return {'data': csv_input, 'status': 200}

def find_name_indices(headers_lower):
    """
    find the indices of the name column(s); the naming conventions I allow rn are a bit limited
    # NOTE: perhaps extend this later
    """
    name_columns = []
    if 'name' in headers_lower:
        name_columns = [headers_lower.index('name')]
    elif 'student name' in headers_lower:
        name_columns = [headers_lower.index('student name')]
    elif 'student' in headers_lower:
        name_columns = [headers_lower.index('student')]
    elif 'firstname' in headers_lower and 'lastname' in headers_lower:
        name_columns = [headers_lower.index('firstname'), headers_lower.index('lastname')]
    elif 'first name' in headers_lower and 'last name' in headers_lower:
        name_columns = [headers_lower.index('first name'), headers_lower.index('last name')]
    elif 'first' in headers_lower and 'last' in headers_lower:
        name_columns = [headers_lower.index('first'), headers_lower.index('last')]
    else:
        return {'error': 'CSV must have either "Name" column or "FirstName" and "LastName" columns', 'status': 400}
    return name_columns

def find_data_attributes(headers_lower, name_indices, student_attributes):
    attributes_indices = [i for i, header in enumerate(headers_lower) if header in student_attributes] # get the indices of the attributes columns
    availabilities_indices = [i for i, header in enumerate(headers_lower) if i not in name_indices and i not in attributes_indices]
    return attributes_indices, availabilities_indices

def parse_student_data(data, given_attributes):
    headers_lower = [str(header).strip().lower() for header in data[0]] # first row of data is headers, make lower case and strip whitespace

    # check that the name column(s) exist, and figure out which ones they are
    name_indices = find_name_indices(headers_lower)
    if isinstance(name_indices, dict):
        return {'error': name_indices['error'], 'status': name_indices['status']}

    # check if there are any student attributes not in headers_lower
    for attr in given_attributes:
        if attr not in headers_lower:
            return {'error': f'student attribute {attr} not found in the csv file. please check the format and try again.', 'status': 400}

    # get attributes and availabilities indices
    attribute_indices, availability_indices = find_data_attributes(headers_lower, name_indices, given_attributes)

    # now make the csv into a df
    df = pd.DataFrame(data[1:], columns=headers_lower)  # type: ignore

    # merge multiple name columns into one if needed
    if len(name_indices) > 1:
        # merge multiple name columns into one
        name_values = df.iloc[:, name_indices].apply(lambda row: ' '.join(row.astype(str)), axis=1)
        df['name'] = name_values
        # drop the original name columns
        df = df.drop(columns=[headers_lower[i] for i in name_indices])
        name_column = 'name'
    else:
        # single name column
        name_column = headers_lower[name_indices[0]]

    # reorder columns: Name, Attributes, Availabilities
    attribute_columns = [headers_lower[i] for i in attribute_indices]
    availability_columns = [headers_lower[i] for i in availability_indices]
    
    # create the new column order
    new_column_order = [name_column] + attribute_columns + availability_columns
    df = df[new_column_order]

    # handle empty values: replace NaN, None, and empty strings with '0' for attributes and availabilities
    # this ensures that missing data is treated as "not available" or "doesn't have attribute"
    for col in attribute_columns + availability_columns:
        df.loc[:, col] = df.loc[:, col].fillna('0')  
        df.loc[:, col] = df.loc[:, col].replace('', '0')
        # convert Yes/yes/True/true to 1 and No/no/False/false to 0
        df.loc[:, col] = df.loc[:, col].replace({'Yes': '1', 'yes': '1', 'No': '0', 'no': '0', 'True': '1', 'False': '0', 'true': '1', 'false': '0'})
        df.loc[:, col] = df.loc[:, col].astype(str)  

    # get the student data, attributes, availabilities
    student_names = df[name_column].tolist()  
    student_attributes = df[attribute_columns].to_dict(orient='records') if attribute_columns else []  # type: ignore
    student_availabilities = df[availability_columns].to_dict(orient='records') if availability_columns else []  # type: ignore

    # filter out students with no availability and track them separately
    filtered_names = []
    filtered_attributes = []
    filtered_availabilities = []
    unassigned_students = []
    
    for i, avail in enumerate(student_availabilities):
        if all(str(v).strip() == '0' for v in avail.values()):
            # student has no availability - add to unassigned list
            unassigned_students.append({
                'name': student_names[i],
                'attributes': student_attributes[i] if student_attributes else {},
                'availabilities': avail
            })
        else:
            # student has availability - include in filtered data
            filtered_names.append(student_names[i])
            if student_attributes:
                filtered_attributes.append(student_attributes[i])
            filtered_availabilities.append(avail)
    
    # if no students have availability, return error
    if not filtered_names:
        return {'error': 'No students have any available times. Please ensure at least one student has available time slots.', 'status': 400}

    return {
        'df': df,
        'student_names': filtered_names,
        'student_attributes': filtered_attributes,
        'student_availabilities': filtered_availabilities,
        'unassigned_students': unassigned_students,
    }

def parse_attribute_constraints(request, given_attributes):
    # Create a case-insensitive lookup for form keys
    form_dict_lower = {k.lower(): v for k, v in request.form.items()}
    
    # get the constraints for each of the student attributes
    attribute_constraints = {}
    for attr in given_attributes:
        attr_constraints = {}
        
        # check for min constraint for this attribute
        min_key = f'{attr}_min_per_group'
        if min_key in form_dict_lower:
            attr_constraints['min_per_group'] = int(form_dict_lower[min_key])
        
        # check for max constraint for this attribute  
        max_key = f'{attr}_max_per_group'
        if max_key in form_dict_lower:
            attr_constraints['max_per_group'] = int(form_dict_lower[max_key])
        
        # only add if constraints were specified
        if attr_constraints:
            attribute_constraints[attr] = attr_constraints
            attribute_constraints[attr] = attr_constraints
    
    return attribute_constraints

def parse_all_constraints(request, num_students, num_availabilities, given_attributes):
    """
    parse the different kinds of constraints: group sizes, number of groups, counts per attribute (individual and combined)
    """
    if 'group_size_max' in request.form:
        group_size_max = int(request.form['group_size_max'])
    else:
        group_size_max = num_students

    if 'group_size_min' in request.form:
        group_size_min = int(request.form['group_size_min'])
    else:
        group_size_min = 1

    if 'group_count_min' in request.form:
        group_count_min = int(request.form['group_count_min'])
    else:
        group_count_min = 1

    if 'group_count_max' in request.form:
        group_count_max = int(request.form['group_count_max'])
    else:
        group_count_max = num_availabilities

    attribute_constraints = parse_attribute_constraints(request, given_attributes)

    combined_constraints = []
    if 'combined_constraints' in request.form:
        try:
            combined_constraints = json.loads(request.form['combined_constraints'])
        except Exception:
            combined_constraints = []

    constraints = SchedulingConstraints(attribute_constraints, group_size_min, group_size_max, group_count_min, group_count_max, combined_constraints)
    return constraints
