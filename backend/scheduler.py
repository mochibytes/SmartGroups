from typing import List, Dict, Set, Tuple, Optional, Any
from constraint_parser import SchedulingConstraints
from ortools.sat.python import cp_model

class GroupScheduler:
    def __init__(self, student_data, constraints):
        """
        initialize the scheduler with student data and constraints
        student_data: dict with 'names', 'attributes', 'availabilities' 
        constraints: SchedulingConstraints object
        """
        self.student_data = student_data
        self.constraints = constraints
        self.num_students = len(student_data['names'])
        self.time_slots = self._extract_time_slots()
        self.num_time_slots = len(self.time_slots)
        self.num_time_slots = len(self.time_slots)
        
    def _extract_time_slots(self):
        return list(self.student_data['availabilities'][0].keys())
    
    def _get_student_availability(self, student_idx, time_slot):
        """
        check if student student_idx is available at time_slot
        """
        if student_idx >= len(self.student_data['availabilities']):
            return False
        
        avail_data = self.student_data['availabilities'][student_idx]
        return str(avail_data.get(time_slot, 0)) == '1'
    
    def _get_student_attribute(self, student_idx, attribute):
        """
        check if student student_idx has 1 for attribute
        """
        if student_idx >= len(self.student_data['attributes']):
            return False
        
        attr_data = self.student_data['attributes'][student_idx]
        value = attr_data.get(attribute, 0)
        return str(int(value)) == '1'
    
    def schedule(self):
        """
        generate groups based on constraints using ortools sat solver
        """
        model = cp_model.CpModel()
        
        # Variables
        max_groups = min(self.constraints.group_count_max, self.num_students) if self.constraints.group_count_max else self.num_students
        
        # student_in_group[s][g] = 1 if student s is in group g
        student_in_group = {}
        for s in range(self.num_students):
            student_in_group[s] = {}
            for g in range(max_groups):
                student_in_group[s][g] = model.NewBoolVar(f'student_{s}_in_group_{g}')
        
        # group_uses_time[g][t] = 1 if group g uses time slot t
        group_uses_time = {}
        for g in range(max_groups):
            group_uses_time[g] = {}
            for t in range(self.num_time_slots):
                group_uses_time[g][t] = model.NewBoolVar(f'group_{g}_uses_time_{t}')
        
        # group_active[g] = 1 if group g is used (b.c. can have up to max_groups number of groups)
        group_active = {}
        for g in range(max_groups):
            group_active[g] = model.NewBoolVar(f'group_{g}_active')
        
        # Constraints
        
        # 1. each student is in exactly one group
        for s in range(self.num_students):
            model.Add(sum(student_in_group[s][g] for g in range(max_groups)) == 1) # i.e. sum of indicators for specific student should be 1
        
        # 2. each group uses exactly one time slot
        for g in range(max_groups):
            model.Add(sum(group_uses_time[g][t] for t in range(self.num_time_slots)) == group_active[g])
        
        # 3. group size constraints
        for g in range(max_groups):
            group_size = sum(student_in_group[s][g] for s in range(self.num_students))
            
            # if group is active, enforce size constraints
            model.Add(group_size >= self.constraints.group_size_min).OnlyEnforceIf(group_active[g])
            if self.constraints.group_size_max:
                model.Add(group_size <= self.constraints.group_size_max).OnlyEnforceIf(group_active[g])
            
            # if group is not active, it has size 0
            model.Add(group_size == 0).OnlyEnforceIf(group_active[g].Not())
            
        
        # 4. group count constraints
        total_groups = sum(group_active[g] for g in range(max_groups))
        model.Add(total_groups >= self.constraints.group_count_min)
        if self.constraints.group_count_max:
            model.Add(total_groups <= self.constraints.group_count_max)
        
        # 5. availability constraints
        for s in range(self.num_students):
            for g in range(max_groups):
                for t in range(self.num_time_slots):
                    # if student s is in group g and group g uses time t,
                    # then student s must be available at time t
                    if not self._get_student_availability(s, self.time_slots[t]):
                        model.Add(student_in_group[s][g] + group_uses_time[g][t] <= 1)
        
        # 6. attribute constraints
        attribute_constraints = self.constraints.get_attribute_constraints()
        for attr, constraints in attribute_constraints.items():
            for g in range(max_groups):
                group_attr_count = sum(student_in_group[s][g] for s in range(self.num_students) 
                            if self._get_student_attribute(s, attr))
                
                if 'min_per_group' in constraints:
                    # Only enforce minimum if group is active
                    model.Add(group_attr_count >= constraints['min_per_group']).OnlyEnforceIf(group_active[g])
                if 'max_per_group' in constraints:
                    # Only enforce maximum if group is active
                    model.Add(group_attr_count <= constraints['max_per_group']).OnlyEnforceIf(group_active[g])

        # 7. combined attribute constraints! added this in case individual constraints are not expressive enough
        combined_constraints = self.constraints.get_combined_constraints()
        for combined in combined_constraints:
            attrs = combined.get('attributes', [])
            min_val = combined.get('min')
            max_val = combined.get('max')
            for g in range(max_groups):
                group_combined_count = sum(
                    student_in_group[s][g]
                    for s in range(self.num_students)
                    if any(self._get_student_attribute(s, attr) for attr in attrs)
                )
                group_size = sum(student_in_group[s][g] for s in range(self.num_students))
                
                if min_val is not None:
                    # Enforce minimum constraint: if group has any students, it must meet the minimum
                    group_has_students = model.NewBoolVar(f'group_{g}_has_students_combined')
                    model.Add(group_size >= 1).OnlyEnforceIf(group_has_students)
                    model.Add(group_size == 0).OnlyEnforceIf(group_has_students.Not())
                    model.Add(group_combined_count >= min_val).OnlyEnforceIf(group_has_students)
                if max_val is not None:
                    model.Add(group_combined_count <= max_val).OnlyEnforceIf(group_active[g])
        
        # solve for best solution
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            return self._format_solution(solver, student_in_group, group_uses_time, group_active, max_groups)
        else:
            # detailed error reporting to help user adjust their constraints
            reasons = []
            if self.constraints.group_size_min > self.num_students:
                reasons.append(f"Minimum group size ({self.constraints.group_size_min}) is greater than the number of students ({self.num_students}).")
            if self.constraints.group_count_max and self.constraints.group_count_max < self.constraints.group_count_min:
                reasons.append(f"Maximum group count ({self.constraints.group_count_max}) is less than the minimum group count ({self.constraints.group_count_min}).")
            # attribute constraints issues
            for attr, cons in self.constraints.get_attribute_constraints().items():
                count_with_attr = sum(1 for s in self.student_data['attributes'] if str(s.get(attr, 0)) == '1')
                if 'min_per_group' in cons and count_with_attr < cons['min_per_group'] * self.constraints.group_count_min:
                    reasons.append(f"Not enough students with attribute '{attr}' to satisfy the minimum per group ({cons['min_per_group']}).")
                if 'max_per_group' in cons and cons['max_per_group'] < 1:
                    reasons.append(f"Maximum per group for attribute '{attr}' is less than 1.")
            if not reasons:
                reasons.append("The combination of constraints may be too strict or incompatible with the data.")
            return {'error': 'No valid solution found with the given constraints. Possible reasons: ' + ' '.join(reasons)}
    
    def _format_solution(self, solver, student_in_group, group_uses_time, group_active, max_groups):
        """format the solution into group ids, time slots they're assigned to, students in each group"""
        groups = []
        
        for g in range(max_groups):
            if solver.Value(group_active[g]):
                # Find students in this group
                group_students = []
                for s in range(self.num_students):
                    if solver.Value(student_in_group[s][g]):
                        student_name = self.student_data['names'][s]
                        student_attrs = (self.student_data['attributes'][s] 
                                       if s < len(self.student_data['attributes']) else {})
                        student_avail = (self.student_data['availabilities'][s] 
                                       if s < len(self.student_data['availabilities']) else {})
                        
                        group_students.append({
                            'name': student_name,
                            'attributes': student_attrs,
                            'availabilities': student_avail
                        })
                
                # Find time slot for this group
                time_slot = 'Not assigned'
                for t in range(self.num_time_slots):
                    if solver.Value(group_uses_time[g][t]):
                        time_slot = self.time_slots[t]
                        break
                
                groups.append({
                    'group_id': g + 1,  # 1-indexed for display
                    'time_slot': time_slot,
                    'students': group_students,
                    'size': len(group_students)
                })
        
        # Sort groups by ID for consistent output
        groups.sort(key=lambda x: x['group_id'])
        
        return {
            'groups': groups,
            'constraints_applied': self.constraints.get_attribute_constraints(),
            'total_students': self.num_students,
            'total_groups': len(groups),
            'group_size_range': self.constraints.get_group_size_constraints(),
            'group_count_range': self.constraints.get_group_count_constraints()
        }