#!/usr/bin/env python3
"""CDK application for the low-cost Campus Medical Assistance demo."""

import aws_cdk as cdk

from campus_medical_stack import CampusMedicalDemoStack


app = cdk.App()
CampusMedicalDemoStack(app, "CampusMedicalDemo", image_tag=app.node.try_get_context("imageTag") or "campus-medical-demo-v9")
app.synth()
