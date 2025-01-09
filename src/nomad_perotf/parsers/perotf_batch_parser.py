#!/usr/bin/env python3
"""
Created on Fri Sep 27 09:08:03 2024

@author: a2853
"""

#
# Copyright The NOMAD Authors.
#
# This file is part of NOMAD. See https://nomad-lab.eu for further info.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import pandas as pd
from baseclasses import LayerProperties, PubChemPureSubstanceSectionCustom
from baseclasses.atmosphere import Atmosphere
from baseclasses.helper.utilities import create_archive
from baseclasses.material_processes_misc import (
    AirKnifeGasQuenching,
    Annealing,
    AntiSolventQuenching,
    GasQuenchingWithNozzle,
    PlasmaCleaning,
    SolutionCleaning,
    UVCleaning,
    VacuumQuenching,
)
from baseclasses.solution import Solution, SolutionChemical
from baseclasses.vapour_based_deposition.atomic_layer_deposition import (
    ALDMaterial,
    ALDPropertiesIris,
)
from baseclasses.vapour_based_deposition.evaporation import (
    InorganicEvaporation,
    OrganicEvaporation,
)
from baseclasses.vapour_based_deposition.sputtering import SputteringProcess
from baseclasses.wet_chemical_deposition import PrecursorSolution
from baseclasses.wet_chemical_deposition.dip_coating import DipCoatingProperties
from baseclasses.wet_chemical_deposition.inkjet_printing import (
    InkjetPrintingProperties,
    PrintHeadPath,
    PrintHeadProperties,
)
from baseclasses.wet_chemical_deposition.slot_die_coating import (
    SlotDieCoatingProperties,
)
from baseclasses.wet_chemical_deposition.spin_coating import SpinCoatingRecipeSteps
from nomad.datamodel import EntryArchive
from nomad.datamodel.data import (
    EntryData,
)
from nomad.datamodel.metainfo.basesections import (
    CompositeSystemReference,
    Entity,
)
from nomad.metainfo import (
    Quantity,
)
from nomad.parsing import MatchingParser

from nomad_perotf.schema_packages.perotf_package import (
    peroTF_ALD,
    peroTF_Batch,
    peroTF_Cleaning,
    peroTF_DipCoating,
    peroTF_Evaporation,
    peroTF_InkjetPrinting,
    peroTF_Process,
    peroTF_Sample,
    peroTF_SlotDieCoating,
    peroTF_SpinCoating,
    peroTF_Sputtering,
    peroTF_Substrate,
)

"""
This is a hello world style example for an example parser/converter.
"""


def get_entry_id_from_file_name(file_name, upload_id):
    from nomad.utils import hash

    return hash(upload_id, file_name)


def get_reference(upload_id, file_name):
    entry_id = get_entry_id_from_file_name(file_name, upload_id)
    return f'../uploads/{upload_id}/archive/{entry_id}#data'


def convert_quantity(value, factor):
    try:
        return float(value) * factor
    except Exception:
        return None


def get_value(data, key, default=None, number=True):
    try:
        if key not in data:
            return default
        if pd.isna(data[key]):
            return default
        if number:
            return float(data[key])
        return str(data[key]).strip()
    except Exception as e:
        raise e


def map_basic_sample(data, substrate_name, upload_id):
    archive = peroTF_Sample(
        name=data['Nomad ID'],
        lab_id=data['Nomad ID'],
        substrate=get_reference(upload_id, substrate_name),
        description=get_value(data, 'Variation', None, False),
    )
    return (data['Nomad ID'], archive)


def map_batch(batch_ids, batch_id, upload_id):
    archive = peroTF_Batch(
        name=batch_id,
        lab_id=batch_id,
        entities=[
            CompositeSystemReference(
                reference=get_reference(upload_id, f'{lab_id}.archive.json'),
                lab_id=lab_id,
            )
            for lab_id in batch_ids
        ],
    )
    return (batch_id, archive)


def map_solutions(data):
    solvents = []
    solutes = []
    for col in data.index:
        if col.lower().startswith('solvent'):
            solvents.append(' '.join(col.split(' ')[:2]))
        if col.lower().startswith('solute'):
            solutes.append(' '.join(col.split(' ')[:2]))

    final_solvents = []
    final_solutes = []
    for solvent in sorted(set(solvents)):
        if not get_value(data, f'{solvent} name', None, False) and not get_value(
            data, f'{solvent} volume [uL]', None
        ):
            continue
        final_solvents.append(
            SolutionChemical(
                chemical_2=PubChemPureSubstanceSectionCustom(
                    name=get_value(data, f'{solvent} name', None, False),
                    load_data=False,
                ),
                chemical_volume=convert_quantity(
                    get_value(data, f'{solvent} volume [uL]', None), 1 / 1000
                ),
            )
        )
    for solute in sorted(set(solutes)):
        if not get_value(data, f'{solute} type', None, False) and not get_value(
            data, f'{solute} Concentration [mM]', None
        ):
            continue
        final_solutes.append(
            SolutionChemical(
                chemical_2=PubChemPureSubstanceSectionCustom(
                    name=get_value(data, f'{solute} type', None, False), load_data=False
                ),
                concentration_mol=convert_quantity(
                    get_value(data, f'{solute} Concentration [mM]', None), 1 / 1000
                ),
            )
        )

    archive = Solution(solvent=final_solvents, solute=final_solutes)

    return archive


def map_spin_coating(i, j, lab_ids, data, upload_id):
    archive = peroTF_SpinCoating(
        name='spin coating ' + get_value(data, 'Material name', '', False),
        location=get_value(data, 'Tool/GB name', '', False),
        positon_in_experimental_plan=i,
        description=get_value(data, 'Notes', '', False),
        samples=[
            CompositeSystemReference(
                reference=get_reference(upload_id, f'{lab_id}.archive.json'),
                lab_id=lab_id,
            )
            for lab_id in lab_ids
        ],
        layer=[
            LayerProperties(
                layer_type=get_value(data, 'Layer type', None, False),
                layer_material_name=get_value(data, 'Material name', None, False),
            )
        ],
        solution=[
            PrecursorSolution(
                solution_details=map_solutions(data),  # check unit
                # check unit
                solution_volume=convert_quantity(
                    get_value(data, 'Solution volume [um]', None), 1 / 1000
                ),
            )
        ],
        annealing=Annealing(
            temperature=get_value(data, 'Annealing temperature [°C]', None),
            time=convert_quantity(get_value(data, 'Annealing time [min]', None), 60),
            atmosphere=get_value(data, 'Annealing athmosphere', None, False),
        ),
        recipe_steps=[
            SpinCoatingRecipeSteps(
                speed=get_value(data, f'Rotation speed {step}[rpm]', None),
                time=get_value(data, f'Rotation time {step}[s]', None),
                acceleration=get_value(data, f'Acceleration {step}[rpm/s]', None),
            )
            for step in ['', '1 ', '2 ', '3 ', '4 ']
            if get_value(data, f'Rotation time {step}[s]')
        ],
    )
    if get_value(data, 'Anti solvent name', None, False):
        archive.quenching = AntiSolventQuenching(
            anti_solvent_volume=get_value(data, 'Anti solvent volume [ml]', None),
            anti_solvent_dropping_time=get_value(
                data, 'Anti solvent dropping time [s]', None
            ),
            anti_solvent_dropping_height=get_value(
                data, 'Anti solvent dropping heigt [mm]', None
            ),
            anti_solvent_dropping_flow_rate=get_value(
                data, 'Anti solvent dropping speed [ul/s]', None
            ),
            anti_solvent_2=PubChemPureSubstanceSectionCustom(
                name=get_value(data, 'Anti solvent name', None, False), load_data=False
            ),
        )
    if get_value(data, 'Vacuum quenching duration [s]', None, False):
        archive.quenching = VacuumQuenching(
            start_time=get_value(data, 'Vacuum quenching start time [s]', None),
            duration=get_value(data, 'Vacuum quenching duration [s]', None),
            pressure=get_value(data, 'Vacuum quenching pressure [bar]', None),
        )

    if get_value(data, 'Gas', None, False):
        archive.quenching = GasQuenchingWithNozzle(
            starting_delay=get_value(data, 'Gas quenching start time [s]', None),
            flow_rate=get_value(data, 'Gas quenching flow rate [ml/s]', None),
            height=get_value(data, 'Gas quenching height [mm]', None),
            duration=get_value(data, 'Gas quenching duration [s]', None),
            pressure=get_value(data, 'Gas quenching pressure [bar]', None),
            velocity=get_value(data, 'Gas quenching velocity [m/s]', None),
            nozzle_shape=get_value(data, 'Nozzle shape', None, False),
            nozzle_size=get_value(data, 'Nozzle size [mm²]', None, False),
            gas=get_value(data, 'Gas', None, False),
        )

    material = get_value(data, 'Material name', '', False)
    return (f'{i}_{j}_spin_coating_{material}', archive)


def map_sdc(i, j, lab_ids, data, upload_id):
    archive = peroTF_SlotDieCoating(
        name='slot die coating ' + get_value(data, 'Material name', '', False),
        location=get_value(data, 'Tool/GB name', '', False),
        positon_in_experimental_plan=i,
        description=get_value(data, 'Notes', None, False),
        samples=[
            CompositeSystemReference(
                reference=get_reference(upload_id, f'{lab_id}.archive.json'),
                lab_id=lab_id,
            )
            for lab_id in lab_ids
        ],
        solution=[
            PrecursorSolution(
                solution_details=map_solutions(data),  # check unit
                # check unit
                solution_volume=convert_quantity(
                    get_value(data, 'Solution volume [um]', None), 1 / 1000
                ),
            )
        ],
        layer=[
            LayerProperties(
                layer_type=get_value(data, 'Layer type', None, False),
                layer_material_name=get_value(data, 'Material name', None, False),
            )
        ],
        annealing=Annealing(
            temperature=get_value(data, 'Annealing temperature [°C]', None),
            time=convert_quantity(get_value(data, 'Annealing time [min]', None), 60),
        ),
        properties=SlotDieCoatingProperties(
            flow_rate=convert_quantity(data.get('Flow rate [ul/min]', None), 1 / 1000),
            slot_die_head_distance_to_thinfilm=get_value(data, 'Head gap [mm]'),
            slot_die_head_speed=get_value(data, 'Speed [mm/s]'),
        ),
        quenching=AirKnifeGasQuenching(
            air_knife_angle=get_value(data, 'Air knife angle [°]', None),
            bead_volume=get_value(data, 'Bead volume [mm/s]', None),
            drying_speed=get_value(data, 'Drying speed [cm/min]', None),
            air_knife_distance_to_thin_film=convert_quantity(
                data.get('Air knife gap [cm]', None), 10000
            ),
        ),
    )
    material = get_value(data, 'Material name', '', False)
    return (f'{i}_{j}_slot_die_coating_{material}', archive)


def map_inkjet_printing(i, j, lab_ids, data, upload_id):
    archive = peroTF_InkjetPrinting(
        name='inkjet printing ' + get_value(data, 'Material name', '', False),
        location=get_value(data, 'Tool/GB name', '', False),
        positon_in_experimental_plan=i,
        description=get_value(data, 'Notes', None, False),
        samples=[
            CompositeSystemReference(
                reference=get_reference(upload_id, f'{lab_id}.archive.json'),
                lab_id=lab_id,
            )
            for lab_id in lab_ids
        ],
        solution=[
            PrecursorSolution(
                solution_details=map_solutions(data),  # check unit
                # check unit
                solution_volume=convert_quantity(
                    get_value(data, 'Solution volume [um]', None), 1 / 1000
                ),
            )
        ],
        layer=[
            LayerProperties(
                layer_type=get_value(data, 'Layer type', None, False),
                layer_material_name=get_value(data, 'Material name', None, False),
            )
        ],
        properties=InkjetPrintingProperties(
            print_head_properties=PrintHeadProperties(
                number_of_active_print_nozzles=get_value(
                    data, 'Number of active nozzles', None
                ),
                print_nozzle_drop_frequency=get_value(
                    data, 'Droplet per second [1/s]', None
                ),
                print_nozzle_drop_volume=get_value(data, 'Droplet volume [pl]', None),
                print_head_temperature=get_value(data, 'Nozzle temperature [°C]', None),
                print_head_name=get_value(data, 'Printhead name', None, False),
            ),
            cartridge_pressure=get_value(data, 'Ink reservoir pressure [bar]', None),
            substrate_temperature=get_value(data, 'Table temperature [°C]', None),
            drop_density=get_value(data, 'Droplet density [dpi]', None),
            printed_area=get_value(data, 'Printed area [mm²]', None),
        ),
        print_head_path=PrintHeadPath(
            quality_factor=get_value(data, 'Quality factor', None, False)
        ),
        atmosphere=Atmosphere(
            relative_humidity=get_value(data, 'rel. humidity [%]', None)
        ),
        annealing=Annealing(
            temperature=get_value(data, 'Annealing temperature [°C]', None),
            time=convert_quantity(get_value(data, 'Annealing time [min]', None), 60),
            atmosphere=get_value(data, 'Annealing athmosphere', None, False),
        ),
    )
    material = get_value(data, 'Material name', '', False)
    return (f'{i}_{j}_inkjet_printing_{material}', archive)


def map_cleaning(i, j, lab_ids, data, upload_id):
    archive = peroTF_Cleaning(
        name='Cleaning',
        positon_in_experimental_plan=i,
        location=get_value(data, 'Tool/GB name', '', False),
        description=get_value(data, 'Notes', '', False),
        samples=[
            CompositeSystemReference(
                reference=get_reference(upload_id, f'{lab_id}.archive.json'),
                lab_id=lab_id,
            )
            for lab_id in lab_ids
        ],
        cleaning=[
            SolutionCleaning(
                time=get_value(data, f'Time {i} [s]', None),
                temperature=get_value(data, f'Temperature {i} [°C]', None),
                solvent_2=PubChemPureSubstanceSectionCustom(
                    name=get_value(data, f'Solvent {i}', None, False), load_data=False
                ),
            )
            for i in range(10)
            if get_value(data, f'Solvent {i}', None, False)
        ],
        cleaning_uv=[UVCleaning(time=get_value(data, 'UV-Ozone Time [s]', None))],
        cleaning_plasma=[
            PlasmaCleaning(
                time=get_value(data, 'Gas-Plasma Time [s]', None),
                power=get_value(data, 'Gas-Plasma Power [W]', None),
                plasma_type=get_value(data, 'Gas-Plasma Gas', None, False),
            )
        ],
    )
    return (f'{i}_{j}_cleaning', archive)


def map_substrate(data):
    archive = peroTF_Substrate(
        name='Substrate '
        + get_value(data, 'Sample dimension', '', False)
        + ' '
        + get_value(data, 'Substrate material', '', False)
        + ' '
        + get_value(data, 'Substrate conductive layer', '', False),
        solar_cell_area=get_value(data, 'Sample area [cm^2]', ''),
        substrate=get_value(data, 'Substrate material', '', False),
        conducting_material=[get_value(data, 'Substrate conductive layer', '', False)],
    )
    return archive


def map_evaporation(i, j, lab_ids, data, upload_id):
    archive = peroTF_Evaporation(
        name='evaporation ' + get_value(data, 'Material name', '', False),
        location=get_value(data, 'Tool/GB name', '', False),
        positon_in_experimental_plan=i,
        description=get_value(data, 'Notes', '', False),
        samples=[
            CompositeSystemReference(
                reference=get_reference(upload_id, f'{lab_id}.archive.json'),
                lab_id=lab_id,
            )
            for lab_id in lab_ids
        ],
        layer=[
            LayerProperties(
                layer_type=get_value(data, 'Layer type', None, False),
                layer_material_name=get_value(data, 'Material name', None, False),
            )
        ],
    )
    evaporation = None
    if get_value(data, 'Organic', '', False).lower().startswith('n') or get_value(
        data, 'Organic', '', False
    ).lower().startswith('0'):
        evaporation = InorganicEvaporation()
        archive.inorganic_evaporation = [evaporation]

    if get_value(data, 'Organic', '', False).lower().startswith('y') or get_value(
        data, 'Organic', '', False
    ).lower().startswith('1'):
        evaporation = OrganicEvaporation(
            temparature=[get_value(data, 'Temperature [°C]', None)] * 2
            if get_value(data, 'Temperature [°C]', None)
            else None
        )

        archive.organic_evaporation = [evaporation]

    evaporation.thickness = get_value(data, 'Thickness [nm]')
    evaporation.start_rate = get_value(data, 'Rate [angstrom/s]')
    evaporation.chemical_2 = PubChemPureSubstanceSectionCustom(
        name=get_value(data, 'Material name', None, False), load_data=False
    )
    if get_value(data, 'Organic', '', False).lower().startswith('n') or get_value(
        data, 'Organic', '', False
    ).lower().startswith('0'):
        archive.inorganic_evaporation = [evaporation]

    if get_value(data, 'Organic', '', False).lower().startswith('y') or get_value(
        data, 'Organic', '', False
    ).lower().startswith('1'):
        archive.organic_evaporation = [evaporation]

    material = get_value(data, 'Material name', '', False)
    return (f'{i}_{j}_evaporation_{material}', archive)


def map_sputtering(i, j, lab_ids, data, upload_id):
    archive = peroTF_Sputtering(
        name='sputtering ' + get_value(data, 'Material name', '', False),
        positon_in_experimental_plan=i,
        location=get_value(data, 'Tool/GB name', '', False),
        description=get_value(data, 'Notes', '', False),
        samples=[
            CompositeSystemReference(
                reference=get_reference(upload_id, f'{lab_id}.archive.json'),
                lab_id=lab_id,
            )
            for lab_id in lab_ids
        ],
        layer=[
            LayerProperties(
                layer_type=get_value(data, 'Layer type', None, False),
                layer_material_name=get_value(data, 'Material name', None, False),
            )
        ],
    )
    process = SputteringProcess(
        thickness=get_value(data, 'Thickness [nm]'),
        gas_flow_rate=get_value(data, 'Gas flow rate [cm^3/min]'),
        rotation_rate=get_value(data, 'Rotation rate [rpm]'),
        power=get_value(data, 'Power [W]'),
        temperature=get_value(data, 'Temperature [°C]'),
        deposition_time=get_value(data, 'Deposition time [s]'),
        burn_in_time=get_value(data, 'Burn in time [s]'),
        pressure=get_value(data, 'Pressure [mbar]'),
        target_2=PubChemPureSubstanceSectionCustom(
            name=get_value(data, 'Material name', None, False), load_data=False
        ),
        gas_2=PubChemPureSubstanceSectionCustom(
            name=get_value(data, 'Gas', None, False), load_data=False
        ),
    )
    archive.processes = [process]
    material = get_value(data, 'Material name', '', False)
    return (f'{i}_{j}_sputtering_{material}', archive)


def map_dip_coating(i, j, lab_ids, data, upload_id):
    archive = peroTF_DipCoating(
        name='dip coating ' + get_value(data, 'Material name', '', False),
        location=get_value(data, 'Tool/GB name', '', False),
        positon_in_experimental_plan=i,
        description=get_value(data, 'Notes', None, False),
        samples=[
            CompositeSystemReference(
                reference=get_reference(upload_id, f'{lab_id}.archive.json'),
                lab_id=lab_id,
            )
            for lab_id in lab_ids
        ],
        solution=[
            PrecursorSolution(
                solution_details=map_solutions(data),  # check unit
                # check unit
                solution_volume=convert_quantity(
                    get_value(data, 'Solution volume [um]', None), 1 / 1000
                ),
            )
        ],
        layer=[
            LayerProperties(
                layer_type=get_value(data, 'Layer type', None, False),
                layer_material_name=get_value(data, 'Material name', None, False),
            )
        ],
        properties=DipCoatingProperties(
            time=convert_quantity(get_value(data, 'Dipping duration [s]'), 1 / 60),
        ),
        annealing=Annealing(
            temperature=get_value(data, 'Annealing temperature [°C]', None),
            time=convert_quantity(get_value(data, 'Annealing time [min]', None), 60),
            atmosphere=get_value(data, 'Annealing athmosphere', None, False),
        ),
    )
    material = get_value(data, 'Material name', '', False)
    return (f'{i}_{j}_dip_coating_{material}', archive)


# def map_laser_scribing(i, j, lab_ids, data, upload_id):
#     archive = HySprint_LaserScribing(
#         name='laser scribing',
#         positon_in_experimental_plan=i,
#         samples=[
#             CompositeSystemReference(
#                 reference=get_reference(upload_id, f'{lab_id}.archive.json'),
#                 lab_id=lab_id,
#             )
#             for lab_id in lab_ids
#         ],
#         properties=LaserScribingProperties(
#             laser_wavelength=get_value(data, 'Laser wavelength [nm]', None),
#             laser_pulse_time=get_value(data, 'Laser pulse time [ps]', None),
#             laser_pulse_frequency=get_value(data,
#                   'Laser pulse frequency [kHz]', None),
#             speed=get_value(data, 'Speed [mm/s]', None),
#             fluence=get_value(data, 'Fluence [J/cm2]', None),
#             power_in_percent=get_value(data, 'Power [%]', None),
#         ),
#     )

#     return (f'{i}_{j}_laser_scribing', archive)


def map_atomic_layer_deposition(i, j, lab_ids, data, upload_id):
    archive = peroTF_ALD(
        name='atomic layer deposition '
        + get_value(data, 'Material name', '', number=False),
        location=get_value(data, 'Tool/GB name', '', False),
        positon_in_experimental_plan=i,
        description=get_value(data, 'Notes', '', number=False),
        samples=[
            CompositeSystemReference(
                reference=get_reference(upload_id, f'{lab_id}.archive.json'),
                lab_id=lab_id,
            )
            for lab_id in lab_ids
        ],
        layer=[
            LayerProperties(
                layer_type=get_value(data, 'Layer type', None, number=False),
                layer_material_name=get_value(
                    data, 'Material name', None, number=False
                ),
            )
        ],
        properties=ALDPropertiesIris(
            source=get_value(data, 'Source', None, number=False),
            thickness=get_value(data, 'Thickness [nm]', None),
            temperature=get_value(data, 'Temperature [°C]', None),
            rate=get_value(data, 'Rate [A/s]', None),
            time=get_value(data, 'Time [s]', None),
            number_of_cycles=get_value(data, 'Number of cycles', None),
            material=ALDMaterial(
                material=PubChemPureSubstanceSectionCustom(
                    name=get_value(data, 'Precursor 1', None, number=False),
                    load_data=False,
                ),
                pulse_duration=get_value(data, 'Pulse duration 1 [s]', None),
                manifold_temperature=get_value(
                    data, 'Manifold temperature 1 [°C]', None
                ),
                bottle_temperature=get_value(data, 'Bottle temperature 1 [°C]', None),
            ),
            oxidizer_reducer=ALDMaterial(
                material=PubChemPureSubstanceSectionCustom(
                    name=get_value(
                        data, 'Precursor 2 (Oxidizer/Reducer)', None, number=False
                    ),
                    load_data=False,
                ),
                pulse_duration=get_value(data, 'Pulse duration 2 [s]', None),
                manifold_temperature=get_value(
                    data, 'Manifold temperature 2 [°C]', None
                ),
            ),
        ),
    )
    material = get_value(data, 'Material name', '', number=False)
    return (f'{i}_{j}_ALD_{material}', archive)


def map_generic(i, j, lab_ids, data, upload_id):
    archive = peroTF_Process(
        name=get_value(data, 'Name', '', False),
        positon_in_experimental_plan=i,
        description=get_value(data, 'Notes', '', False),
        samples=[
            CompositeSystemReference(
                reference=get_reference(upload_id, f'{lab_id}.archive.json'),
                lab_id=lab_id,
            )
            for lab_id in lab_ids
        ],
    )
    return (f'{i}_{j}_generic_process', archive)


class RawHySprintExperiment(EntryData):
    processed_archive = Quantity(type=Entity, shape=['*'])


class PeroTFExperimentParser(MatchingParser):
    def is_mainfile(
        self,
        filename: str,
        mime: str,
        buffer: bytes,
        decoded_buffer: str,
        compression: str = None,
    ):
        is_mainfile_super = super().is_mainfile(
            filename, mime, buffer, decoded_buffer, compression
        )
        if not is_mainfile_super:
            return False
        try:
            df = pd.read_excel(filename, header=[0, 1])
            df['Experiment Info']['Nomad ID'].dropna().to_list()
        except Exception:
            return False
        return True

    def parse(self, mainfile: str, archive: EntryArchive, logger):
        upload_id = archive.metadata.upload_id
        # xls = pd.ExcelFile(mainfile)
        df = pd.read_excel(mainfile, header=[0, 1])

        sample_ids = df['Experiment Info']['Nomad ID'].dropna().to_list()
        batch_id = '_'.join(sample_ids[0].split('_')[:-1])
        archives = [map_batch(sample_ids, batch_id, upload_id)]
        substrates = []
        substrates_col = [
            'Sample dimension',
            'Sample area [cm^2]',
            'Substrate material',
            'Substrate conductive layer',
        ]
        for i, sub in (
            df['Experiment Info'][substrates_col].drop_duplicates().iterrows()
        ):
            if pd.isna(sub).all():
                continue
            substrates.append((f'{i}_substrate', sub, map_substrate(sub)))

        def find_substrate(d):
            for s in substrates:
                if d.equals(s[1]):
                    return s[0]

        for i, row in df['Experiment Info'].iterrows():
            if pd.isna(row).all():
                continue
            substrate_name = (
                find_substrate(
                    row[
                        [
                            'Sample dimension',
                            'Sample area [cm^2]',
                            'Substrate material',
                            'Substrate conductive layer',
                        ]
                    ]
                )
                + '.archive.json'
            )
            archives.append(map_basic_sample(row, substrate_name, upload_id))

        for i, col in enumerate(df.columns.get_level_values(0).unique()):
            if col == 'Experiment Info':
                continue

            df_dropped = df[col].drop_duplicates()
            for j, row in df_dropped.iterrows():
                lab_ids = [
                    x['Experiment Info']['Nomad ID']
                    for _, x in df[['Experiment Info', col]].iterrows()
                    if x[col].astype('object').equals(row.astype('object'))
                ]
                if 'Cleaning' in col:
                    archives.append(map_cleaning(i, j, lab_ids, row, upload_id))

                # if 'Laser Scribing' in col:
                #     archives.append(map_laser_scribing(i, j, lab_ids, row, upload_id))

                if 'Generic Process' in col:  # move up
                    archives.append(map_generic(i, j, lab_ids, row, upload_id))

                if pd.isna(row.get('Material name')):
                    continue

                if 'Evaporation' in col:
                    archives.append(map_evaporation(i, j, lab_ids, row, upload_id))

                if 'Spin Coating' in col:
                    archives.append(map_spin_coating(i, j, lab_ids, row, upload_id))

                if 'Inkjet Printing' in col:
                    archives.append(map_inkjet_printing(i, j, lab_ids, row, upload_id))

                if 'Dip Coating' in col:
                    archives.append(map_dip_coating(i, j, lab_ids, row, upload_id))

                # if 'Slot Die Coating' in col:
                #     archives.append(map_sdc(i, j, lab_ids, row, upload_id))

                if 'Sputtering' in col:
                    archives.append(map_sputtering(i, j, lab_ids, row, upload_id))

                if 'ALD' in col:
                    archives.append(
                        map_atomic_layer_deposition(i, j, lab_ids, row, upload_id)
                    )

        refs = []
        for subs in substrates:
            file_name = f'{subs[0]}.archive.json'
            create_archive(subs[2], archive, file_name)
            refs.append(get_reference(upload_id, file_name))

        for a in archives:
            file_name = f'{a[0]}.archive.json'
            create_archive(a[1], archive, file_name)
            refs.append(get_reference(upload_id, file_name))

        archive.data = RawHySprintExperiment(processed_archive=refs)
