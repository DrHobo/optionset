#!/usr/bin/env python3
"""
Measure how long it takes program to run.

Author: Matthew C. Jones
Email: matt.c.jones.aoe@gmail.com

:copyright: 2020 by Optionset authors, see AUTHORS for more details.
:license: GPLv3, see LICENSE for more details.
"""

import time
import numpy as np

from runtests import run_cmd

times = []
N = 100
for i in range(N):
    start_time = time.time()
    output_str, _ = run_cmd("../optionset/optionset.py -q @op 2")
    this_time = time.time() - start_time
    times.append(this_time)
    print("Time [s]: {:1.5f}".format(this_time))

print("Avg time [s]: {:1.5f}".format(np.mean(times)))
