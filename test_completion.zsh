_generate_foo_completions() {
  local idx=$1; shift
  local words=( "$@" )
  local current_word=${words[idx]}

  local array=(
    '0_summarise_imgs_and_annots.py
    summar
    1_organize_into_images_annots.py
    organize_folder
    2_rename_files.py
    rename_files
    3_validate_data_structure.py
    validate
    analyze_synth_base_images.py
    build_inference_records.py
    check_and_move_images.py
    check_and_move_images
    collection_annots_overview.py
    compare_images_between_two_dirs.py
    config_backup.py
    dataset_gen.sh
    filter_synth_images.py
    find_duplicate_imgs_in_collection.py
    fix_category_annotations.py
    generate_config_summary.py
    generate_data_yaml_with_log.py
    keep_newest_duplicates.py
    merge_annots_from_tags.py
    merge_captures.py
    move_n_random_images_to_val.py
    review_annotations.py
    review_img_annots_pairs.py
    run.sh
    segment.py
    sort_images_from_insights.py
    sync_and_sort_images.sh
    sync
    sync_image_files.py
    train_conditional_notesmd_test.py
    txt_file_path_manipulation.py
    update_bulk_download.py'
  )
  for elem in "${array[@]}"; do
    if [[ $elem == "$current_word"* ]]; then echo "$elem"; fi
  done
}

_complete_foo_bash() {
  local raw=($(_generate_foo_completions "$COMP_CWORD" "${COMP_WORDS[@]}"))
  COMPREPLY=( "${raw[@]}" )
}

_complete_foo_zsh() {
  local -a raw
  raw=($(_generate_foo_completions "$CURRENT" "${words[@]}"))
  compadd -- $raw
}

if [ -n "${ZSH_VERSION:-}" ]; then
  autoload -Uz compinit
  compinit
  compdef _complete_foo_zsh aris
elif [ -n "${BASH_VERSION:-}" ]; then
  complete -F _complete_foo_bash aris
fi 