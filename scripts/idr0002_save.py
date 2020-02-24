#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#
# Copyright (c) 2020 University of Dundee.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
# FPBioimage was originally published in
# <https://www.nature.com/nphoton/journal/v11/n2/full/nphoton.2016.273.html>.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
# Version: 1.0
#
import os
import tempfile
import pandas
import warnings

import matplotlib

from getpass import getpass

# Import OMERO Python BlitzGateway
from omero.gateway import BlitzGateway
from omero.grid import DoubleColumn, ImageColumn, LongColumn, WellColumn
from omero.constants.namespaces import NSBULKANNOTATIONS
from omero.gateway import FileAnnotationWrapper
from omero.model import OriginalFileI

# module used to inject OMERO image planes into Cell Profiler Pipeline
from cellprofiler.modules.injectimage import InjectImage

# Import Cell Profiler Dependencies
import cellprofiler.preferences as cpprefs
import cellprofiler.pipeline as cpp
cpprefs.set_headless()


def connect(hostname, username, password):
    conn = BlitzGateway(username, password,
                        host=hostname, secure=True)
    conn.connect()
    return conn


def load_pipeline(pipeline_path):
    pipeline = cpp.Pipeline(),
    pipeline.load(pipeline_path)
    # Remove first 4 modules: Images, Metadata, NamesAndTypes, Groups...
    # (replaced by InjectImage module below)
    for i in range(4):
        print('Remove module: ', pipeline.modules()[0].module_name)
        pipeline.remove_module(1)
    print('Pipeline modules:')
    for module in pipeline.modules():
        print(module.module_num, module.module_name)
    return pipeline


def analyze(plate, pipeline):
    warnings.filterwarnings('ignore')
    # Set Cell Output Directory
    new_output_directory = os.path.normcase(tempfile.mkdtemp())
    cpprefs.set_default_output_directory(new_output_directory)

    files = list()
    wells = list(plate.listChildren())
    wells = wells[0:5]  # use the first 5 wells
    for count, well in enumerate(wells):
        # Load a single Image per Well
        image = well.getImage(0)
        pixels = image.getPrimaryPixels()
        size_c = image.getSizeC()
        # For each Image in OMERO, we copy pipeline and inject image modules
        pipeline_copy = pipeline.copy()
        # Inject image for each Channel (pipeline only handles 2 channels)
        for c in range(0, size_c):
            plane = pixels.getPlane(0, c, 0)
            image_name = image.getName()
            # Name of the channel expected in the pipeline
            if c == 0:
                image_name = 'OrigBlue'
            if c == 1:
                image_name = 'OrigGreen'
            inject_image_module = InjectImage(image_name, plane)
            inject_image_module.set_module_num(1)
            pipeline_copy.add_module(inject_image_module)
        pipeline_copy.run()

        # Results obtained as CSV from Cell Profiler
        path = new_output_directory + '/Nuclei.csv'
        f = pandas.read_csv(path, index_col=None, header=0)
        f['Image'] = image.getId()
        f['Well'] = well.getId()
        f['Cell_Count'] = len(f.index)
        files.append(f)
    return files


def calculate_stats(files):
    Nuclei = pandas.DataFrame()
    Nuclei = pandas.concat(files, ignore_index=True)
    Nuclei.describe()
    matplotlib.rcParams['figure.figsize'] = (32.0, 30.0)
    df = Nuclei.drop(['Image', 'ImageNumber', 'Well', 'ObjectNumber',
                      'Number_Object_Number', 'Classify_PH3Neg',
                      'Classify_PH3Pos'], axis=1)
    df.hist()


def save_results(conn, summary, plate):
    cols = []
    for col in summary.columns:
        if col == 'Image':
            cols.append(ImageColumn(col, '', summary[col]))
        elif col == 'Well':
            cols.append(WellColumn(col, '', summary[col]))
        elif summary[col].dtype == 'int64':
            cols.append(LongColumn(col, '', summary[col]))
        elif summary[col].dtype == 'float64':
            cols.append(DoubleColumn(col, '', summary[col]))

    resources = conn.c.sf.sharedResources()
    repository_id = resources.repositories().descriptions[0].getId().getValue()
    table_name = "idr0002_cellprofiler"
    table = resources.newTable(repository_id, table_name)
    table.initialize(cols)
    table.addData(cols)
    # Link the table to the plate
    orig_file = table.getOriginalFile()
    file_ann = FileAnnotationWrapper(conn)
    file_ann.setNs(NSBULKANNOTATIONS)
    file_ann._obj.file = OriginalFileI(orig_file.id.val, False)
    file_ann.save()
    plate.linkAnnotation(file_ann)
    table.close()


def main():
    # Collect user credentials
    username = raw_input("Username: ")
    password = getpass("OMERO Password: ")
    plate_id = raw_input("Plate ID: ")
    host = 'wss://workshop.openmicroscopy.org/omero-ws'
    # Connect to the server
    conn = connect(host, username, password)

    # Read the pipeline
    pipeline_path = "../notebooks/pipelines/ExamplePercentPositive.cppipe"
    pipeline = load_pipeline(pipeline_path)

    # Load the plate
    plate = conn.getObject("Plate", plate_id)
    files = analyze(plate, pipeline)

    # Calculate stats
    Nuclei = calculate_stats(files)

    # Save the result back to OMERO
    summary = Nuclei.groupby('Image').mean()
    save_results(conn, summary, plate)


if __name__ == "__main__":
    main()
