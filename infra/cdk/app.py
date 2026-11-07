#!/usr/bin/env python3
"""CDK application for the low-cost Campus Medical Assistance demo."""

import aws_cdk as cdk

from campus_medical_stack import CampusMedicalDemoStack


app = cdk.App()
CampusMedicalDemoStack(app, "CampusMedicalDemo")
app.synth()
